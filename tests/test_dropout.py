from pathlib import Path

import pytest

from yt_emby.config import ConfigError, resolve_settings
from yt_emby.dropout import (
    emby_season_dir,
    format_dry_run_row,
    format_season_plan,
    resolve_emby_target,
    run_dropout,
)
from yt_emby.dropout_manifest import filter_dropout_manifest, load_dropout_manifest, season_page_url
from yt_emby.extract import DropoutListing
from yt_emby.style import strip_ansi


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
):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    return resolve_settings(
        library=str(tmp_path / "lib"),
        old_dir=str(tmp_path / "old"),
        ffmpeg_location=str(ffmpeg),
        dry_run=dry_run,
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
    assert series.name == "Dimension 20"
    assert season_page_url(series, series.seasons[0]).endswith("/season:28")
    assert series.seasons[1].to_season is None
    remap = series.seasons[1].remap[0]
    assert remap.to_season == 0
    assert remap.to_episode == 70


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
    from yt_emby.dropout_manifest import DropoutRemap, DropoutSeason

    listing = DropoutListing(
        url="https://watch.dropout.tv/x/videos/welcome",
        title="Welcome to the Wastes",
        dropout_episode=1,
    )
    mapped = DropoutSeason(
        dropout=29,
        remap=(DropoutRemap(1, 0, 70),),
    )
    assert resolve_emby_target(listing, mapped) == (0, 70)
    defaulted = DropoutSeason(dropout=28, to_season=27)
    assert resolve_emby_target(listing, defaulted) == (27, 1)
    listing2 = DropoutListing(url="https://x", title="Other", dropout_episode=2)
    assert resolve_emby_target(listing2, mapped) == (29, 2)
    omitted = DropoutSeason(dropout=26, remap=(DropoutRemap(21, 0, 63),))
    assert resolve_emby_target(
        DropoutListing(url="https://x", title="On High We Go", dropout_episode=1),
        omitted,
    ) == (26, 1)
    assert resolve_emby_target(listing, DropoutSeason(url="https://x", remap=())) is None


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
    leftover = tmp_path / "yt-emby-dropout-killed"
    leftover.mkdir()
    (leftover / "partial.temp.mkv").write_bytes(b"x")
    monkeypatch.setattr("yt_emby.download.tempfile.gettempdir", lambda: str(tmp_path))

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
    from yt_emby.extract import extract_dropout_season

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
    from yt_emby.extract import extract_dropout_season

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
    from yt_emby.extract import parse_dropout_browse_titles

    html = """
    <a href="https://watch.dropout.tv/x/videos/welcome-to-the-wastes" class="browse-item-link"
       data-track-event-properties="{&quot;label&quot;:&quot;Welcome to the Wastes&quot;}">
      <img alt="Welcome to the Wastes" src="https://img.example/ep.jpg" />
    </a>
    """
    titles = parse_dropout_browse_titles(html)
    assert titles["https://watch.dropout.tv/x/videos/welcome-to-the-wastes"] == "Welcome to the Wastes"


def test_extract_dropout_season_falls_back_to_url_slug() -> None:
    from yt_emby.extract import extract_dropout_season

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
    from yt_emby import extract as extract_mod

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
    from yt_emby.dropout_manifest import DropoutRemap, DropoutSeason

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
    assert "keeping" not in out


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
    assert [season.dropout for season in filtered.series[0].seasons] == [28]
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
    from yt_emby.cache import DROPOUT_CACHE_FILENAME, load_dropout_season_cache

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
    from yt_emby.cache import (
        LEGACY_DROPOUT_CACHE_FILENAME,
        dropout_listings_to_cache,
        save_dropout_season_cache,
    )

    manifest = load_dropout_manifest(_write_manifest(tmp_path))
    library = tmp_path / "lib"
    library.mkdir()
    series = manifest.series[0]
    seasons = {
        season_page_url(series, season): dropout_listings_to_cache(
            _welcome_extract(season_page_url(series, season))
        )
        for season in series.seasons
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
    from yt_emby import dropout as dropout_mod

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
