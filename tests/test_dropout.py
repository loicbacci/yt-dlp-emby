from pathlib import Path

import pytest

from yt_dlp_emby.config import ConfigError, resolve_settings
from yt_dlp_emby.dropout import (
    emby_season_dir,
    format_season_plan,
    layout_origin,
    layout_series_groups,
    resolve_emby_target,
    run_dropout,
)
from yt_dlp_emby.dropout_manifest import (
    DropoutSeries,
    DropoutSource,
    filter_dropout_manifest,
    load_dropout_manifest,
    season_page_url,
)
from yt_dlp_emby.extract import DropoutListing
from yt_dlp_emby.log import format_dry_run_row
from yt_dlp_emby.style import strip_ansi


def _write_manifest(tmp_path: Path) -> Path:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 28
        to_season: 27
      - dropout: 29
        remap:
          - dropout_episode: 1
            to_season: 0
            to_episode: 70
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    return path


def _settings(
    tmp_path: Path,
    *,
    dry_run: bool = False,
    quiet: bool = True,
    silent: bool = False,
    verbose: bool = False,
    debug: bool = False,
    force_refetch: bool = False,
    layout: bool = False,
):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    return resolve_settings(
        library=str(tmp_path / "lib"),
        old_dir=str(tmp_path / "old"),
        ffmpeg_location=str(ffmpeg),
        dry_run=dry_run,
        layout=layout,
        quiet=quiet,
        silent=silent,
        verbose=verbose,
        debug=debug,
        force_refetch=force_refetch,
        environ={},
        cwd=tmp_path,
        use_default_config=False,
        auto_cookies=False,
    )


def test_load_manifest_series_url_and_remap(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    series = manifest.series[0]
    source = series.sources[0]
    assert series.name == "Dimension 20"
    assert season_page_url(source, source.seasons[0]).endswith("/season:28")
    assert source.seasons[1].to_season is None
    remap = source.seasons[1].remap[0]
    assert remap.to_season == 0
    assert remap.to_episode == 70
    assert remap.title is None
    assert source.seasons[0].only_episodes is None
    assert source.seasons[1].only_episodes is None


def test_load_manifest_only_episodes(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - url: https://watch.dropout.tv/dimension-20-fantasy-high/season:2
        to_season: 7
        only_episodes: [18, 19, 18]
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    season = load_dropout_manifest(path).series[0].sources[0].seasons[0]
    assert season.url.endswith("/season:2")
    assert season.to_season == 7
    assert season.only_episodes == (18, 19)


def test_dropout_manifest_rejects_empty_only_episodes(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 28
        to_season: 27
        only_episodes: []
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="only_episodes"):
        load_dropout_manifest(path)


def test_load_manifest_remap_title(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 29
        remap:
          - dropout_episode: 1
            to_season: 0
            to_episode: 70
            title: D20 on a Bus
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    remap = load_dropout_manifest(path).series[0].sources[0].seasons[0].remap[0]
    assert remap.title == "D20 on a Bus"


def test_dropout_manifest_rejects_empty_cookies(tmp_path: Path) -> None:
    cookies = tmp_path / "dropout-cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
cookies: dropout-cookies.txt
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 28
        to_season: 27
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="empty"):
        load_dropout_manifest(path)


def test_emby_season_dir_specials(tmp_path: Path) -> None:
    series = tmp_path / "Dimension 20 [tvdbid=354216]"
    assert emby_season_dir(series, 0) == series / "Specials"
    assert emby_season_dir(series, 27) == series / "Season 27"


def test_resolve_remap_and_default_to_season() -> None:
    from yt_dlp_emby.dropout_manifest import DropoutRemap, DropoutSeason

    listing = DropoutListing(
        url="https://watch.dropout.tv/x/videos/welcome",
        title="Welcome to the Wastes",
        dropout_episode=1,
    )
    mapped = DropoutSeason(
        dropout=29,
        remap=(DropoutRemap(1, 0, 70),),
    )
    assert resolve_emby_target(listing, mapped) == (0, 70, "Welcome to the Wastes")
    defaulted = DropoutSeason(dropout=28, to_season=27)
    assert resolve_emby_target(listing, defaulted) == (27, 1, "Welcome to the Wastes")
    listing2 = DropoutListing(url="https://x", title="Other", dropout_episode=2)
    assert resolve_emby_target(listing2, mapped) == (29, 2, "Other")
    omitted = DropoutSeason(dropout=26, remap=(DropoutRemap(21, 0, 63),))
    assert resolve_emby_target(
        DropoutListing(url="https://x", title="On High We Go", dropout_episode=1),
        omitted,
    ) == (26, 1, "On High We Go")
    assert resolve_emby_target(listing, DropoutSeason(url="https://x", remap=())) is None
    named = DropoutSeason(
        dropout=29,
        remap=(DropoutRemap(1, 0, 70, title="D20 on a Bus"),),
    )
    assert resolve_emby_target(listing, named) == (0, 70, "D20 on a Bus")
    skipped = DropoutSeason(
        dropout=29,
        remap=(DropoutRemap(2, skip=True),),
    )
    assert resolve_emby_target(
        DropoutListing(url="https://x", title="Bonus", dropout_episode=2),
        skipped,
    ) == "skip"


def test_layout_origin_only_when_remapped() -> None:
    from yt_dlp_emby.dropout_manifest import DropoutSeason

    listing = DropoutListing(url="https://x", title="Welcome", dropout_episode=1)
    identity = DropoutSeason(dropout=17, to_season=17)
    assert layout_origin(identity, listing, 17, 1) is None
    remapped = DropoutSeason(dropout=17, to_season=17)
    assert layout_origin(remapped, listing, 0, 28) == "season 17 E01"
    shifted = DropoutSeason(dropout=28, to_season=27)
    assert layout_origin(shifted, listing, 27, 1) == "season 28 E01"
    url_only = DropoutSeason(url="https://x", to_season=7)
    fireside = DropoutListing(url="https://x", title="Fireside", dropout_episode=18)
    assert layout_origin(url_only, fireside, 7, 18) is None
    assert layout_origin(url_only, fireside, 0, 70) == "E18"


def test_layout_series_groups_by_name_or_path() -> None:
    shared_path = DropoutSeries(
        name="Dimension 20 Main",
        path="Dimension 20 [tvdbid=354216]",
        sources=(DropoutSource(url="https://watch.dropout.tv/main", seasons=()),),
    )
    shared_name = DropoutSeries(
        name="Dimension 20",
        path="Dimension 20 [tvdbid=354216]",
        sources=(DropoutSource(url="https://watch.dropout.tv/main", seasons=()),),
    )
    other_path = DropoutSeries(
        name="Dimension 20",
        path="Dimension 20 Alt [tvdbid=354216]",
        sources=(DropoutSource(url="https://watch.dropout.tv/alt", seasons=()),),
    )
    separate = DropoutSeries(
        name="Other Show",
        path="Other Show [tvdbid=1]",
        sources=(DropoutSource(url="https://watch.dropout.tv/other", seasons=()),),
    )
    by_path = layout_series_groups((shared_path, shared_name))
    assert by_path[(shared_path.name, shared_path.path)][0] == by_path[
        (shared_name.name, shared_name.path)
    ][0]
    assert by_path[(shared_path.name, shared_path.path)][1] == "Dimension 20 [tvdbid=354216]"

    by_name = layout_series_groups((shared_name, other_path))
    assert by_name[(shared_name.name, shared_name.path)][0] == by_name[
        (other_path.name, other_path.path)
    ][0]
    assert by_name[(shared_name.name, shared_name.path)][1] == "Dimension 20"

    mixed = layout_series_groups((shared_path, shared_name, other_path, separate))
    assert mixed[(shared_path.name, shared_path.path)][0] == mixed[
        (shared_name.name, shared_name.path)
    ][0]
    assert mixed[(shared_name.name, shared_name.path)][0] == mixed[
        (other_path.name, other_path.path)
    ][0]
    assert mixed[(separate.name, separate.path)][0] != mixed[
        (shared_path.name, shared_path.path)
    ][0]


def test_load_manifest_remap_skip(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 29
        remap:
          - dropout_episode: 2
            skip: true
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    remap = load_dropout_manifest(path).series[0].sources[0].seasons[0].remap[0]
    assert remap.dropout_episode == 2
    assert remap.skip is True
    assert remap.to_season is None
    assert remap.to_episode is None


def test_dropout_remap_skip_omits_episode(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 29
        to_season: 29
        remap:
          - dropout_episode: 2
            skip: true
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/main-ep",
                title="Main Episode",
                dropout_episode=1,
            ),
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/bonus",
                title="Bonus Episode",
                dropout_episode=2,
            ),
        ]

    def fake_download(url: str, dest_stem: Path, _settings: object, **_kwargs: object) -> dict:
        calls.append(url)
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        dest_stem.with_suffix(".mkv").write_bytes(b"new")
        return {"id": "ep"}

    assert (
        run_dropout(
            load_dropout_manifest(path),
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 0
    )
    assert calls == ["https://watch.dropout.tv/x/videos/main-ep"]
    assert (
        tmp_path
        / "lib"
        / "Dimension 20 [tvdbid=354216]"
        / "Season 29"
        / "Dimension 20 - S29E02 - Bonus Episode.mkv"
    ).exists() is False


def test_dropout_skips_existing_and_force_redownloads(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    settings = _settings(tmp_path)
    series_dir = tmp_path / "lib" / "Dimension 20 [tvdbid=354216]"
    dest = (
        series_dir
        / "Season 27"
        / "Dimension 20 - S27E01 - Welcome to the Wastes.mkv"
    )
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old")
    calls: list[str] = []

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if url.endswith("/season:28"):
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                    title="Welcome to the Wastes",
                    dropout_episode=1,
                )
            ]
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/special",
                title="Special",
                dropout_episode=1,
            )
        ]

    def fake_download(url: str, dest_stem: Path, _settings: object, **kwargs: object) -> dict:
        calls.append(url)
        assert kwargs.get("subtitleslangs") == ["all"]
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        dest_stem.with_suffix(".mkv").write_bytes(b"new")
        return {"id": "ep"}

    assert (
        run_dropout(
            manifest,
            settings,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 0
    )
    assert dest.read_bytes() == b"old"
    assert all("/welcome-to-the-wastes" not in url for url in calls)

    special = series_dir / "Specials" / "Dimension 20 - S00E70 - Special.mkv"
    assert special.is_file()

    calls.clear()
    assert (
        run_dropout(
            manifest,
            settings,
            force=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 0
    )
    assert any("/welcome-to-the-wastes" in url for url in calls)
    assert dest.read_bytes() == b"new"


def test_dropout_only_episodes_downloads_listed_numbers(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - url: https://watch.dropout.tv/dimension-20-fantasy-high/season:2
        to_season: 7
        only_episodes: [18]
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/main-ep",
                title="Main Episode",
                dropout_episode=1,
            ),
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/fireside",
                title="Fireside Chat",
                dropout_episode=18,
            ),
        ]

    def fake_download(url: str, dest_stem: Path, _settings: object, **_kwargs: object) -> dict:
        calls.append(url)
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        dest_stem.with_suffix(".mkv").write_bytes(b"new")
        return {"id": "ep"}

    assert (
        run_dropout(
            load_dropout_manifest(path),
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 0
    )
    assert calls == ["https://watch.dropout.tv/x/videos/fireside"]
    dest = (
        tmp_path
        / "lib"
        / "Dimension 20 [tvdbid=354216]"
        / "Season 7"
        / "Dimension 20 - S07E18 - Fireside Chat.mkv"
    )
    assert dest.is_file()
    assert not (
        tmp_path
        / "lib"
        / "Dimension 20 [tvdbid=354216]"
        / "Season 7"
        / "Dimension 20 - S07E01 - Main Episode.mkv"
    ).exists()


def test_dropout_urls_download_into_same_path(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    urls:
      - url: https://watch.dropout.tv/dimension-20-the-complete-series
        seasons:
          - dropout: 1
            to_season: 1
      - url: https://watch.dropout.tv/dimension-20-live-complete-collection
        seasons:
          - dropout: 1
            remap:
              - dropout_episode: 1
                to_season: 0
                to_episode: 48
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    calls: list[str] = []

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if "complete-series" in url:
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/welcome",
                    title="Welcome",
                    dropout_episode=1,
                )
            ]
        if "live-complete" in url:
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/live-show",
                    title="Live Show",
                    dropout_episode=1,
                )
            ]
        raise AssertionError(url)

    def fake_download(url: str, dest_stem: Path, _settings: object, **_kwargs: object) -> dict:
        calls.append(url)
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        dest_stem.with_suffix(".mkv").write_bytes(b"new")
        return {"id": "ep"}

    assert (
        run_dropout(
            load_dropout_manifest(path),
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 0
    )
    series_dir = tmp_path / "lib" / "Dimension 20 [tvdbid=354216]"
    assert (
        series_dir / "Season 1" / "Dimension 20 - S01E01 - Welcome.mkv"
    ).is_file()
    assert (
        series_dir / "Specials" / "Dimension 20 - S00E48 - Live Show.mkv"
    ).is_file()
    assert calls == [
        "https://watch.dropout.tv/x/videos/welcome",
        "https://watch.dropout.tv/x/videos/live-show",
    ]


def test_dropout_dry_run_does_not_download(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    calls: list[str] = []

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            )
        ]

    def fake_download(url: str, dest_stem: Path, _settings: object, **_kwargs: object) -> dict:
        calls.append(url)
        return {"id": "ep"}

    assert (
        run_dropout(
            manifest,
            _settings(tmp_path, dry_run=True),
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 0
    )
    assert calls == []
    assert not (tmp_path / "lib").exists()
    assert (tmp_path / "cache" / "dropout.json").is_file()


def test_dropout_cleans_stale_tmp_on_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leftover = tmp_path / "yt-dlp-emby-dropout-killed"
    leftover.mkdir()
    (leftover / "partial.temp.mkv").write_bytes(b"x")
    monkeypatch.setattr("yt_dlp_emby.download.tempfile.gettempdir", lambda: str(tmp_path))

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return []

    assert (
        run_dropout(
            load_dropout_manifest(_write_manifest(tmp_path)),
            _settings(tmp_path, dry_run=True),
            extract_fn=fake_extract,
            download_fn=lambda *_a, **_k: {},
        )
        == 0
    )
    assert not leftover.exists()


def test_extract_dropout_season_omits_youtube_clients() -> None:
    from yt_dlp_emby.extract import extract_dropout_season

    seen: dict = {}

    def fake_extract(_url: str, opts: dict) -> dict:
        seen.update(opts)
        return {
            "entries": [
                {
                    "url": "https://watch.dropout.tv/x/videos/ep",
                    "title": "Ep",
                    "episode_number": 3,
                }
            ]
        }

    listed = extract_dropout_season(
        "https://watch.dropout.tv/x/season:1",
        extract_fn=fake_extract,
    )
    assert "extractor_args" not in seen
    assert seen.get("extract_flat") == "in_playlist"
    assert seen.get("skip_download") is True
    assert listed[0].dropout_episode == 3
    assert listed[0].title == "Ep"


def test_extract_dropout_season_falls_back_to_list_order() -> None:
    from yt_dlp_emby.extract import extract_dropout_season

    listed = extract_dropout_season(
        "https://watch.dropout.tv/x/season:1",
        extract_fn=lambda _url, _opts: {
            "entries": [
                {"url": "https://watch.dropout.tv/x/videos/a", "title": "A"},
                {"url": "https://watch.dropout.tv/x/videos/b", "title": "B"},
            ]
        },
    )
    assert [item.dropout_episode for item in listed] == [1, 2]


def test_parse_dropout_browse_titles_uses_on_site_label() -> None:
    from yt_dlp_emby.extract import parse_dropout_browse_titles

    html = """
    <a href="https://watch.dropout.tv/x/videos/welcome-to-the-wastes" class="browse-item-link"
       data-track-event-properties="{&quot;label&quot;:&quot;Welcome to the Wastes&quot;}">
      <img alt="Welcome to the Wastes" src="https://img.example/ep.jpg" />
    </a>
    """
    titles = parse_dropout_browse_titles(html)
    assert titles["https://watch.dropout.tv/x/videos/welcome-to-the-wastes"] == "Welcome to the Wastes"


def test_extract_dropout_season_falls_back_to_url_slug() -> None:
    from yt_dlp_emby.extract import extract_dropout_season

    listed = extract_dropout_season(
        "https://watch.dropout.tv/x/season:1",
        extract_fn=lambda _url, _opts: {
            "entries": [
                {"url": "https://watch.dropout.tv/x/videos/welcome-to-the-wastes"},
            ]
        },
    )
    assert listed[0].title == "welcome to the wastes"


def test_extract_dropout_season_uses_browse_titles_when_yt_dlp_has_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yt_dlp_emby import extract as extract_mod

    def fake_extract(_url: str, _opts: dict) -> dict:
        return {
            "entries": [
                {
                    "url": "https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                    "_type": "url",
                }
            ]
        }

    monkeypatch.setattr(extract_mod, "_ydl_extract", fake_extract)
    monkeypatch.setattr(
        extract_mod,
        "_load_dropout_season_titles",
        lambda _url, _opts: {
            "https://watch.dropout.tv/x/videos/welcome-to-the-wastes": "Welcome to the Wastes"
        },
    )
    listed = extract_mod.extract_dropout_season("https://watch.dropout.tv/x/season:28")
    assert listed[0].title == "Welcome to the Wastes"


def test_format_season_plan_and_dry_run_row() -> None:
    from yt_dlp_emby.dropout_manifest import DropoutRemap, DropoutSeason

    mapped = DropoutSeason(dropout=28, to_season=27)
    assert "season 28 → Season 27" in format_season_plan(
        mapped, skip=12, download=2, unmapped=0
    )
    specials = DropoutSeason(dropout=29, to_season=0)
    assert "Specials" in format_season_plan(specials, skip=0, download=1, unmapped=0)
    remapped = DropoutSeason(dropout=29, remap=(DropoutRemap(1, 0, 70),))
    line = format_season_plan(remapped, skip=0, download=1, unmapped=4, retitled=1)
    assert "remap" in line
    assert "4 unmapped" in line
    assert "1 title differs" in line
    omitted_line = format_season_plan(mapped, skip=0, download=2, unmapped=0, omitted=15)
    assert "15 omitted" in omitted_line
    timed = strip_ansi(
        format_season_plan(
            mapped,
            skip=0,
            download=21,
            unmapped=0,
            listing_source="cached",
            listing_seconds=0.004,
            disk_seconds=1.4,
        )
    )
    assert timed.endswith("cached  1.4s")
    debug = strip_ansi(
        format_season_plan(
            mapped,
            skip=0,
            download=21,
            unmapped=0,
            listing_source="cached",
            listing_seconds=0.004,
            disk_seconds=1.4,
            debug=True,
        )
    )
    assert "cached 4ms  disk 1.4s" in debug
    row = format_dry_run_row("download", "S27E01", "Welcome to the Wastes", "Season 27/")
    assert strip_ansi(row).startswith("download")
    assert "S27E01" in row
    assert "Season 27/" in row
    origin_row = format_dry_run_row(
        "download", "S00E28", "Behind the Scenes: How It Began", "", origin="season 17 E07"
    )
    assert "Season 17/" not in strip_ansi(origin_row)
    assert "(season 17 E07)" in strip_ansi(origin_row)


def test_dropout_dry_run_prints_table(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if url.endswith("/season:28"):
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                    title="Welcome to the Wastes",
                    dropout_episode=1,
                )
            ]
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/special",
                title="Special",
                dropout_episode=1,
            )
        ]

    assert (
        run_dropout(
            manifest,
            _settings(tmp_path, dry_run=True, quiet=False),
            extract_fn=fake_extract,
            download_fn=lambda *_a, **_k: {"id": "nope"},
        )
        == 0
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "Dimension 20" in out
    assert "season 28 → Season 27" in out
    assert "season 29 → remap" in out
    assert "    download" in out
    assert "S27E01" in out
    assert "S00E70" in out
    assert "Season 27/" in out
    assert "Specials/" in out
    assert "fetch" in out
    assert "listing cache" not in out
    assert "Listing 1/2" not in out
    assert "Listing 2/2" not in out
    assert "Done  dry-run  download=2  skip=0" in out


def test_dropout_layout_groups_by_destination(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 17
        to_season: 17
        remap:
          - dropout_episode: 7
            to_season: 0
            to_episode: 28
          - dropout_episode: 8
            skip: true
      - url: https://watch.dropout.tv/extra
        remap:
          - dropout_episode: 1
            to_season: 0
            to_episode: 29
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if "extra" in url:
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/bts-cast",
                    title="Behind the Scenes: The Cast",
                    dropout_episode=1,
                ),
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/unmapped",
                    title="Unmapped Extra",
                    dropout_episode=2,
                ),
            ]
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/seeds",
                title="The Seeds of Conflict",
                dropout_episode=1,
            ),
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/bts-began",
                title="Behind the Scenes: How It Began",
                dropout_episode=7,
            ),
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/skip-me",
                title="Skip This",
                dropout_episode=8,
            ),
        ]

    assert (
        run_dropout(
            load_dropout_manifest(path),
            _settings(tmp_path, layout=True, quiet=False),
            extract_fn=fake_extract,
            download_fn=lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("layout downloaded")
            ),
        )
        == 0
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "Dimension 20" in out
    assert "season 17 →" not in out
    assert "Season 17/" not in out
    assert "Specials/" not in out
    assert "  Season 17" in out
    assert "  Specials" in out
    assert "  unmapped" in out
    assert "S17E01" in out
    assert "The Seeds of Conflict" in out
    assert "(season 17 E01)" not in out
    assert "S00E28" in out
    assert "(season 17 E07)" in out
    assert "S00E29" in out
    assert "Skip This" not in out
    assert "Unmapped Extra" in out
    assert out.index("Season 17") < out.index("Specials")
    assert out.index("Specials") < out.index("unmapped")
    assert out.index("S00E28") < out.index("S00E29")
    assert "Done  dry-run  download=3  skip=0" in out


def test_dropout_layout_combines_same_path_or_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20 Main
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-main
    seasons:
      - dropout: 17
        to_season: 17
  - name: Dimension 20 Extras
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-extras
    seasons:
      - url: https://watch.dropout.tv/extra
        remap:
          - dropout_episode: 1
            to_season: 0
            to_episode: 29
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if "extra" in url:
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/bts-cast",
                    title="Behind the Scenes: The Cast",
                    dropout_episode=1,
                )
            ]
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/seeds",
                title="The Seeds of Conflict",
                dropout_episode=1,
            )
        ]

    run_dropout(
        load_dropout_manifest(path),
        _settings(tmp_path, layout=True, quiet=False),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    out = strip_ansi(capsys.readouterr().out)
    assert out.count("Dimension 20 [tvdbid=354216]") == 1
    assert "Dimension 20 Main" not in out
    assert "Dimension 20 Extras" not in out
    assert "  Season 17" in out
    assert "  Specials" in out
    assert "S17E01" in out
    assert "S00E29" in out
    assert out.index("Season 17") < out.index("Specials")


def test_dropout_layout_debug_keeps_source_plans(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if url.endswith("/season:28"):
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                    title="Welcome to the Wastes",
                    dropout_episode=1,
                )
            ]
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/special",
                title="Special",
                dropout_episode=1,
            )
        ]

    run_dropout(
        manifest,
        _settings(tmp_path, layout=True, quiet=False, debug=True),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "season 28 → Season 27" in out
    assert "season 29 → remap" in out
    assert "  Season 27" in out
    assert "  Specials" in out
    assert "(season 28 E01)" in out
    assert "(season 29 E01)" in out
    assert "Season 27/" not in out


def test_dropout_quiet_prints_summary_not_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            )
        ]

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=True),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "season 28 → Season 27" in out
    assert "S27E01" in out
    assert "S00E70" in out
    assert "Done  dry-run" in out


def _welcome_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
    if url.endswith("/season:28"):
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            )
        ]
    return [
        DropoutListing(
            url="https://watch.dropout.tv/x/videos/special",
            title="Special",
            dropout_episode=1,
        )
    ]


def _seed_episode(tmp_path: Path, folder: str, code: str, title: str) -> Path:
    dest = tmp_path / "lib" / "Dimension 20 [tvdbid=354216]" / folder
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"Dimension 20 - {code} - {title}.mkv"
    path.write_bytes(b"x")
    return path


def test_dropout_dry_run_hides_skip_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    _seed_episode(tmp_path, "Season 27", "S27E01", "Welcome to the Wastes")
    _seed_episode(tmp_path, "Specials", "S00E70", "Special")

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False),
        extract_fn=_welcome_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "    skip" not in out
    assert "    download" not in out
    assert "Done  dry-run  download=0  skip=2" in out


def test_dropout_verbose_dry_run_prints_skip_rows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    _seed_episode(tmp_path, "Season 27", "S27E01", "Welcome to the Wastes")

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False, verbose=True),
        extract_fn=_welcome_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    captured = capsys.readouterr()
    out = strip_ansi(captured.out)
    assert "    skip" in out
    assert "S27E01" in out
    assert "    download" in out
    assert "S00E70" in out
    assert "title changed" not in captured.err


def test_dropout_slug_filename_is_not_title_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    _seed_episode(tmp_path, "Season 27", "S27E01", "welcome to the wastes")

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False),
        extract_fn=_welcome_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    captured = capsys.readouterr()
    out = strip_ansi(captured.out)
    assert "title differs" not in out
    assert "title changed" not in captured.err
    assert "    skip" not in out
    assert "1 skip" in out


def test_dropout_title_differs_counted_not_warned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    _seed_episode(tmp_path, "Season 27", "S27E01", "Old Title")

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False),
        extract_fn=_welcome_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    captured = capsys.readouterr()
    out = strip_ansi(captured.out)
    assert "1 title differs" in out
    assert "title changed" not in captured.err
    assert "    skip" not in out


def test_remap_title_suppresses_title_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 28
        to_season: 27
        remap:
          - dropout_episode: 1
            to_season: 27
            to_episode: 1
            title: Old Title
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    _seed_episode(tmp_path, "Season 27", "S27E01", "Old Title")

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            )
        ]

    run_dropout(
        load_dropout_manifest(path),
        _settings(tmp_path, dry_run=True, quiet=False),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "title differs" not in out
    assert "1 skip" in out


def test_remap_title_used_in_download_filename(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 28
        to_season: 27
        remap:
          - dropout_episode: 1
            to_season: 27
            to_episode: 1
            title: Custom Name
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            )
        ]

    def fake_download(_url: str, dest_stem: Path, _settings: object, **_kwargs: object) -> dict:
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        dest_stem.with_suffix(".mkv").write_bytes(b"new")
        return {"id": "ep"}

    assert (
        run_dropout(
            load_dropout_manifest(path),
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 0
    )
    dest = (
        tmp_path
        / "lib"
        / "Dimension 20 [tvdbid=354216]"
        / "Season 27"
        / "Dimension 20 - S27E01 - Custom Name.mkv"
    )
    assert dest.is_file()
    assert not (
        tmp_path
        / "lib"
        / "Dimension 20 [tvdbid=354216]"
        / "Season 27"
        / "Dimension 20 - S27E01 - Welcome to the Wastes.mkv"
    ).exists()


def test_dropout_verbose_warns_title_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    _seed_episode(tmp_path, "Season 27", "S27E01", "Old Title")

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False, verbose=True),
        extract_fn=_welcome_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    captured = capsys.readouterr()
    out = strip_ansi(captured.out)
    assert "1 title differs" in out
    assert "    skip" in out
    assert "S27E01" in out
    assert "title differs  keeping" in out
    assert "Old Title.mkv" in out
    assert "title changed" not in captured.err
    assert "keeping" not in captured.err


def test_dropout_silent_hides_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            )
        ]

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, silent=True),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_dropout_failed_download_exits_nonzero(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            )
        ]

    def fake_download(*_args: object, **_kwargs: object) -> dict:
        raise RuntimeError("boom")

    assert (
        run_dropout(
            manifest,
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 1
    )


def test_filter_manifest_series_and_season(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    filtered = filter_dropout_manifest(manifest, dropout_seasons=[28])
    assert len(filtered.series) == 1
    assert [
        season.dropout
        for source in filtered.series[0].sources
        for season in source.seasons
    ] == [28]
    named = filter_dropout_manifest(manifest, series_names=["dimension 20"])
    assert named.series[0].name == "Dimension 20"
    with pytest.raises(ConfigError, match="No series/seasons matched"):
        filter_dropout_manifest(manifest, series_names=["Not A Show"])


def test_refuses_missing_series_folder(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    with pytest.raises(ConfigError, match="--create"):
        run_dropout(
            manifest,
            _settings(tmp_path),
            extract_fn=lambda *_a, **_k: [],
            download_fn=lambda *_a, **_k: {"id": "x"},
        )


def test_dropout_auth_error_aborts(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    calls: list[str] = []

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        raise RuntimeError("HTTP Error 403: Forbidden")

    def fake_download(url: str, *_args: object, **_kwargs: object) -> dict:
        calls.append(url)
        return {"id": "x"}

    assert (
        run_dropout(
            manifest,
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 1
    )
    assert calls == []


def test_dropout_download_auth_error_stops_remaining(tmp_path: Path) -> None:
    from yt_dlp_emby.auth import DropoutAuthError

    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    calls: list[str] = []

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if url.endswith("/season:28"):
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                    title="Welcome to the Wastes",
                    dropout_episode=1,
                ),
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/next",
                    title="Next",
                    dropout_episode=2,
                ),
            ]
        return []

    def fake_download(url: str, *_args: object, **_kwargs: object) -> dict:
        calls.append(url)
        raise DropoutAuthError("login required")

    assert (
        run_dropout(
            manifest,
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 1
    )
    assert calls == ["https://watch.dropout.tv/x/videos/welcome-to-the-wastes"]


def test_dropout_download_auth_error_stops_remaining(tmp_path: Path) -> None:
    from yt_dlp_emby.auth import DropoutAuthError

    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    calls: list[str] = []

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if url.endswith("/season:28"):
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                    title="Welcome to the Wastes",
                    dropout_episode=1,
                ),
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/next",
                    title="Next",
                    dropout_episode=2,
                ),
            ]
        return []

    def fake_download(url: str, *_args: object, **_kwargs: object) -> dict:
        calls.append(url)
        raise DropoutAuthError("login required")

    assert (
        run_dropout(
            manifest,
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 1
    )
    assert calls == ["https://watch.dropout.tv/x/videos/welcome-to-the-wastes"]


def test_dropout_title_change_skips_existing_sxxexx(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    series_dir = tmp_path / "lib" / "Dimension 20 [tvdbid=354216]"
    old = series_dir / "Season 27" / "Dimension 20 - S27E01 - Old Title.mkv"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"old")
    calls: list[str] = []

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        if url.endswith("/season:28"):
            return [
                DropoutListing(
                    url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                    title="Welcome to the Wastes",
                    dropout_episode=1,
                )
            ]
        return []

    def fake_download(url: str, dest_stem: Path, *_args: object, **_kwargs: object) -> dict:
        calls.append(url)
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        dest_stem.with_suffix(".mkv").write_bytes(b"new")
        return {"id": "ep"}

    assert (
        run_dropout(
            manifest,
            _settings(tmp_path),
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 0
    )
    assert calls == []
    assert old.read_bytes() == b"old"


def test_dropout_caches_season_listings(tmp_path: Path) -> None:
    from yt_dlp_emby.cache import DROPOUT_CACHE_FILENAME, load_dropout_season_cache

    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    calls: list[str] = []

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        calls.append(url)
        return _welcome_extract(url)

    first = run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    second = run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    assert first == 0
    assert second == 0
    assert len(calls) == 2
    cache_path = tmp_path / "cache" / DROPOUT_CACHE_FILENAME
    assert cache_path.is_file()
    assert not (tmp_path / "lib" / DROPOUT_CACHE_FILENAME).exists()
    cached = load_dropout_season_cache(cache_path)
    assert any("season:28" in key for key in cached)
    assert cached[next(key for key in cached if "season:28" in key)][0]["title"] == (
        "Welcome to the Wastes"
    )

    calls.clear()
    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, force_refetch=True),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    assert len(calls) == 2


def test_dropout_migrates_library_listing_cache(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from yt_dlp_emby.cache import (
        LEGACY_DROPOUT_CACHE_FILENAME,
        dropout_listings_to_cache,
        save_dropout_season_cache,
    )

    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    library = tmp_path / "lib"
    library.mkdir()
    series = manifest.series[0]
    seasons = {
        season_page_url(source, season): dropout_listings_to_cache(
            _welcome_extract(season_page_url(source, season))
        )
        for source in series.sources
        for season in source.seasons
    }
    save_dropout_season_cache(library / LEGACY_DROPOUT_CACHE_FILENAME, seasons)
    calls: list[str] = []

    def fake_extract(url: str, **_kwargs: object) -> list[DropoutListing]:
        calls.append(url)
        return _welcome_extract(url)

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    out = strip_ansi(capsys.readouterr().out)
    assert calls == []
    assert f"moved listing cache from {library / LEGACY_DROPOUT_CACHE_FILENAME}" in out
    assert (tmp_path / "cache" / "dropout.json").is_file()
    assert not (library / LEGACY_DROPOUT_CACHE_FILENAME).exists()
    assert "cached" in out
    assert "fetch" not in out


def test_dropout_interrupt_returns_130(tmp_path: Path) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            )
        ]

    def fake_download(*_args: object, **_kwargs: object) -> dict:
        raise KeyboardInterrupt

    assert (
        run_dropout(
            manifest,
            _settings(tmp_path),
            create=True,
            extract_fn=fake_extract,
            download_fn=fake_download,
        )
        == 130
    )


def test_dropout_season_line_shows_cached_after_fetch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False),
        extract_fn=_welcome_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    first = strip_ansi(capsys.readouterr().out)
    assert "fetch" in first
    assert "cached" not in first
    assert "disk" not in first

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False),
        extract_fn=_welcome_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    second = strip_ansi(capsys.readouterr().out)
    assert "cached" in second
    assert "fetch" not in second
    assert "disk" not in second


def test_dropout_debug_splits_cache_and_disk(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True, quiet=False, debug=True),
        extract_fn=_welcome_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    out = strip_ansi(capsys.readouterr().out)
    assert f"listing cache  {tmp_path / 'cache' / 'dropout.json'}" in out
    assert "seasons" in out
    assert "fetch" in out
    assert "disk" in out


def test_dropout_indexes_each_season_folder_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 28
        to_season: 27
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    manifest = load_dropout_manifest(path)
    _seed_episode(tmp_path, "Season 27", "S27E01", "Welcome to the Wastes")
    _seed_episode(tmp_path, "Season 27", "S27E02", "The Next")
    from yt_dlp_emby import dropout as dropout_mod

    calls: list[Path] = []
    real = dropout_mod.index_episode_mkvs

    def spy(season: Path) -> dict[tuple[int, int], Path]:
        calls.append(season)
        return real(season)

    monkeypatch.setattr(dropout_mod, "index_episode_mkvs", spy)

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
                title="Welcome to the Wastes",
                dropout_episode=1,
            ),
            DropoutListing(
                url="https://watch.dropout.tv/x/videos/next",
                title="The Next",
                dropout_episode=2,
            ),
        ]

    run_dropout(
        manifest,
        _settings(tmp_path, dry_run=True),
        extract_fn=fake_extract,
        download_fn=lambda *_a, **_k: {"id": "nope"},
    )
    assert len(calls) == 1
    assert calls[0].name == "Season 27"
