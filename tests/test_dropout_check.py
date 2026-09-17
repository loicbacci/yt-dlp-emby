from pathlib import Path

import pytest

from yt_dlp_emby.cache import dropout_cache_path, load_dropout_season_cache, save_dropout_season_cache
from yt_dlp_emby.config import ConfigError, resolve_settings
from yt_dlp_emby.dropout_check import check_series_report, run_dropout_check
from yt_dlp_emby.style import CYAN, GREEN, RED, YELLOW, strip_ansi
from yt_dlp_emby.dropout_manifest import (
    DropoutManifest,
    DropoutRemap,
    DropoutSeason,
    DropoutSeries,
    DropoutSource,
    load_dropout_manifest,
    season_page_url,
)
from yt_dlp_emby.sonarr import SonarrEpisode


def _settings(tmp_path: Path, **kwargs):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    values = dict(
        library=str(tmp_path / "lib"),
        old_dir=str(tmp_path / "old"),
        ffmpeg_location=str(ffmpeg),
        environ={},
        cwd=tmp_path,
        use_default_config=False,
        auto_cookies=False,
        sonarr_url="http://localhost:8989",
        sonarr_api_key="test-key",
    )
    values.update(kwargs)
    return resolve_settings(**values)


def _series(
    *,
    name: str = "Game Changer",
    path: str = "Game Changer [tvdbid=361151]",
    tvdb_id: int | None = 361151,
    tvdb_skip: frozenset[tuple[int, int]] = frozenset(),
    url: str = "https://watch.dropout.tv/game-changer",
) -> DropoutSeries:
    return DropoutSeries(
        name=name,
        path=path,
        sources=(DropoutSource(url=url, seasons=(DropoutSeason(dropout=1),)),),
        tvdb_id=tvdb_id,
        tvdb_skip=tvdb_skip,
    )


def _manifest(tmp_path: Path, *series: DropoutSeries) -> DropoutManifest:
    return DropoutManifest(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        series=series,
        path=tmp_path / "dropout.yaml",
    )


def _write_mkv(tmp_path: Path, series_path: str, season: int, episode: int, title: str) -> Path:
    folder = "Specials" if season == 0 else f"Season {season}"
    dest = tmp_path / "lib" / series_path / folder
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / f"Game Changer - S{season:02d}E{episode:02d} - {title}.mkv"
    path.write_bytes(b"x")
    return path


def _seed_listings(
    manifest: DropoutManifest,
    series: DropoutSeries,
    season: DropoutSeason,
    listings: list[dict],
) -> None:
    page = season_page_url(series.sources[0], season)
    path = dropout_cache_path(manifest.path)
    existing = load_dropout_season_cache(path)
    existing[page] = listings
    save_dropout_season_cache(path, existing)


def test_check_missing_special(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 12, "Cut for Time Title"),
            SonarrEpisode(1, 1, "Pilot"),
        ]

    code = run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert "missing" in out
    assert "S00E12" in out
    assert "warning" not in out


def test_check_planned_download_not_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fetch(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(1, 4, "Slug Eater")]

    code = run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert "ok" in out
    assert "missing" not in out


def test_check_remap_dest_without_file_is_not_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(
                    DropoutSeason(
                        dropout=29,
                        remap=(DropoutRemap(1, 0, 70),),
                    ),
                ),
            ),
        ),
        tvdb_id=361151,
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 70, "D20 on a Bus"),
            SonarrEpisode(29, 1, "Placeholder"),
        ]

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert "missing" not in out
    assert "warning" not in out


def test_check_remap_dest_not_in_sonarr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(
                    DropoutSeason(
                        dropout=29,
                        remap=(DropoutRemap(1, 0, 99, title="Ghost Episode"),),
                    ),
                ),
            ),
        ),
        tvdb_id=361151,
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 70, "D20 on a Bus"),
            SonarrEpisode(29, 1, "Placeholder"),
        ]

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert "warning" in out
    assert "S00E99" in out
    assert "not in Sonarr" in out
    assert "Ghost Episode" in out
    assert "S00E70" in out
    assert "missing" in out


def test_check_remap_title_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(
                    DropoutSeason(
                        dropout=29,
                        remap=(DropoutRemap(1, 0, 70, title="Wrong Title"),),
                    ),
                ),
            ),
        ),
        tvdb_id=361151,
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 70, "D20 on a Bus"),
            SonarrEpisode(29, 1, "Placeholder"),
        ]

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert "warning" in out
    assert "S00E70" in out
    assert "Wrong Title" in out
    assert "D20 on a Bus" in out
    assert "missing" not in out


def test_check_remap_title_match_is_ok(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(
                    DropoutSeason(
                        dropout=29,
                        remap=(DropoutRemap(1, 0, 70, title="D20 on a Bus"),),
                    ),
                ),
            ),
        ),
        tvdb_id=361151,
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 70, "D20 on a Bus"),
            SonarrEpisode(29, 1, "Placeholder"),
        ]

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert "ok" in out
    assert "warning" not in out


def test_check_dest_season_not_in_sonarr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(DropoutSeason(dropout=1, to_season=99),),
            ),
        ),
        tvdb_id=361151,
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(1, 1, "Pilot")]

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert "warning" in out
    assert "S99" in out
    assert "not in Sonarr" in out


def test_check_colors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)

    def fetch_ok(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(1, 4, "Slug Eater")]

    run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch_ok)
    ok_out = capsys.readouterr().out
    assert GREEN in ok_out
    assert "ok" in strip_ansi(ok_out)

    def fetch_missing(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 12, "Cut for Time Title"),
            SonarrEpisode(1, 1, "Pilot"),
        ]

    run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch_missing)
    missing_out = capsys.readouterr().out
    assert RED in missing_out
    assert "missing" in strip_ansi(missing_out)

    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(
                    DropoutSeason(dropout=29, remap=(DropoutRemap(1, 0, 99),)),
                ),
            ),
        ),
        tvdb_id=361151,
    )

    def fetch_unknown(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(29, 1, "Placeholder")]

    run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch_unknown)
    warn_out = capsys.readouterr().out
    assert YELLOW in warn_out
    assert "warning" in strip_ansi(warn_out)

    _write_mkv(tmp_path, "Game Changer [tvdbid=361151]", 1, 4, "Filename Title")

    def fetch_names(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(1, 4, "Official Title")]

    run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch_names)
    names_out = capsys.readouterr().out
    assert YELLOW in names_out
    assert "names" in strip_ansi(names_out)

    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(DropoutSeason(dropout=1), DropoutSeason(dropout=4)),
            ),
        ),
        tvdb_id=361151,
    )
    _write_mkv(tmp_path, series.path, 4, 11, "Slug Eater")

    def fetch_sure(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 30, "Slug Eater", air_date="2021-07-13"),
            SonarrEpisode(4, 11, "Slug Eater", air_date="2021-07-13"),
        ]

    run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch_sure)
    sure_out = capsys.readouterr().out
    assert GREEN in sure_out
    assert "add to skip list" in strip_ansi(sure_out)
    assert "maybe" not in strip_ansi(sure_out).split("S00E30", 1)[1].split("\n", 1)[0]

    def fetch_maybe(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(
                0, 30, "Game Changer Season 4: Cut For Time", air_date="2021-07-13"
            ),
            SonarrEpisode(4, 11, "The Official Cast Recording", air_date="2021-07-13"),
        ]

    run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch_maybe)
    maybe_out = capsys.readouterr().out
    assert YELLOW in maybe_out
    assert "maybe" in strip_ansi(maybe_out)

    season = DropoutSeason(dropout=26)
    party = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(season,),
            ),
        ),
        tvdb_id=361151,
    )
    manifest = _manifest(tmp_path, party)
    _seed_listings(
        manifest,
        party,
        season,
        [
            {
                "url": "https://watch.dropout.tv/videos/the-cloudward-crew-confers",
                "title": "The Cloudward Crew Confers",
                "dropout_episode": 3,
            }
        ],
    )

    def fetch_origin(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 64, "The Cloudward Crew Confers"),
            SonarrEpisode(26, 1, "Pilot"),
        ]

    run_dropout_check(manifest, _settings(tmp_path), fetch_fn=fetch_origin)
    origin_out = capsys.readouterr().out
    assert CYAN in origin_out
    assert "season 26 E03" in strip_ansi(origin_out)


def test_check_only_episodes_unlisted_is_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(DropoutSeason(dropout=1, only_episodes=(4,)),),
            ),
        ),
        tvdb_id=361151,
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(1, 4, "Slug Eater"),
            SonarrEpisode(1, 5, "Next One"),
        ]

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert "S01E05" in out
    assert "S01E04" not in out


def test_check_present_not_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_mkv(tmp_path, "Game Changer [tvdbid=361151]", 1, 4, "Slug Eater")

    def fetch(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(1, 4, "Slug Eater")]

    code = run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert "ok" in out
    assert "missing" not in out


def test_check_tvdb_skip_hides_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 12, "Cut for Time Title"),
            SonarrEpisode(1, 1, "Pilot"),
        ]

    series = _series(tvdb_skip=frozenset({(0, 12)}))
    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert "ok" in out
    assert "S00E12" not in out


def test_check_name_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_mkv(tmp_path, "Game Changer [tvdbid=361151]", 1, 4, "Filename Title")

    def fetch(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(1, 4, "Official Title")]

    code = run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert "names" in out
    assert "Filename Title" in out
    assert "Official Title" in out
    _write_mkv(tmp_path, "Game Changer [tvdbid=361151]", 1, 5, "Hello World")

    def fetch_punct(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(1, 5, "Hello, World!")]

    code = run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch_punct)
    out = capsys.readouterr().out
    assert code == 0
    assert "ok" in out


def test_check_skips_series_without_tvdb_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = _series(tvdb_id=None, name="No Id Show", path="No Id Show")

    def fetch(_tvdb_id: int):
        raise AssertionError("should not fetch")

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert "skipped" in out.lower()
    assert "tvdb_id" in out


def test_check_urls_series_is_one_block(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    series = DropoutSeries(
        name="Dimension 20",
        path="Dimension 20 [tvdbid=354216]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/dimension-20-the-complete-series",
                seasons=(DropoutSeason(dropout=1),),
            ),
            DropoutSource(
                url="https://watch.dropout.tv/dimension-20-live-complete-collection",
                seasons=(DropoutSeason(dropout=1),),
            ),
        ),
        tvdb_id=354216,
    )
    _write_mkv(tmp_path, "Dimension 20 [tvdbid=354216]", 1, 1, "Welcome")

    def fetch(_tvdb_id: int):
        return "Dimension 20", [SonarrEpisode(1, 1, "Welcome")]

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("Dimension 20") == 1
    assert "ok" in out


def test_check_merged_path_unions_skip(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Game Changer
    path: Game Changer [tvdbid=361151]
    tvdb_id: 361151
    tvdb_skip:
      - season: 0
        episodes: [12]
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
  - name: Game Changer
    path: Game Changer [tvdbid=361151]
    tvdb_skip:
      - season: 0
        episodes: [13]
    url: https://watch.dropout.tv/game-changer-extras
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 12, "Cut 12"),
            SonarrEpisode(0, 13, "Cut 13"),
            SonarrEpisode(1, 1, "Pilot"),
        ]

    _write_mkv(tmp_path, "Game Changer [tvdbid=361151]", 1, 1, "Pilot")
    code = run_dropout_check(load_dropout_manifest(path), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 0
    assert "S00E12" not in out
    assert "S00E13" not in out
    assert "ok" in out


def test_check_requires_sonarr_settings_when_tvdb_id_present(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path, sonarr_url=None, sonarr_api_key=None)
    code = run_dropout_check(_manifest(tmp_path, _series()), settings)
    err = capsys.readouterr().err
    assert code == 1
    assert "sonarr_url" in err or "Sonarr" in err
    assert "sonarr_api_key" in err or "API" in err


def test_check_does_not_call_dropout_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("Dropout extract should not run")

    monkeypatch.setattr("yt_dlp_emby.extract.extract_dropout_season", boom)
    _write_mkv(tmp_path, "Game Changer [tvdbid=361151]", 1, 1, "Pilot")

    def fetch(_tvdb_id: int):
        return "Game Changer", [SonarrEpisode(1, 1, "Pilot")]

    assert run_dropout_check(_manifest(tmp_path, _series()), _settings(tmp_path), fetch_fn=fetch) == 0


def test_check_suggests_dropout_listing_for_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    season = DropoutSeason(dropout=26)
    series = DropoutSeries(
        name="Dimension 20's Adventuring Party",
        path="Dimension 20's Adventuring Party [tvdbid=391568]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/dimension-20-s-adventuring-party",
                seasons=(season,),
            ),
        ),
        tvdb_id=391568,
    )
    manifest = _manifest(tmp_path, series)
    _seed_listings(
        manifest,
        series,
        season,
        [
            {
                "url": "https://watch.dropout.tv/videos/the-cloudward-crew-confers",
                "title": "The Cloudward Crew Confers",
                "dropout_episode": 3,
            }
        ],
    )

    def fetch(_tvdb_id: int):
        return "Dimension 20's Adventuring Party", [
            SonarrEpisode(0, 64, "The Cloudward Crew Confers"),
            SonarrEpisode(26, 1, "Pilot"),
        ]

    code = run_dropout_check(manifest, _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert "S00E64" in out
    assert "season 26 E03" in out


def test_check_suggests_sonarr_duplicate_by_date(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(DropoutSeason(dropout=1), DropoutSeason(dropout=4)),
            ),
        ),
        tvdb_id=361151,
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(
                0, 30, "Game Changer Season 4: Cut For Time", air_date="2021-07-13"
            ),
            SonarrEpisode(1, 1, "Pilot", air_date="2019-09-20"),
            SonarrEpisode(4, 11, "The Official Cast Recording", air_date="2021-07-13"),
        ]

    code = run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    assert "S00E30" in out
    assert "maybe" in out
    assert "same as S04E11" in out
    assert "skip list" not in out


def test_check_duplicate_on_disk_suggests_skip_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(DropoutSeason(dropout=1), DropoutSeason(dropout=4)),
            ),
        ),
        tvdb_id=361151,
    )
    _write_mkv(tmp_path, series.path, 4, 11, "The Official Cast Recording")

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(
                0, 30, "Game Changer Season 4: Cut For Time", air_date="2021-07-13"
            ),
            SonarrEpisode(1, 1, "Pilot", air_date="2019-09-20"),
            SonarrEpisode(4, 11, "The Official Cast Recording", air_date="2021-07-13"),
        ]

    run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    missing_line = next(line for line in out.splitlines() if "S00E30" in line)
    assert "maybe add to skip list" in missing_line
    assert "S04E11" in missing_line


def test_check_exact_duplicate_on_disk_is_sure_skip_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(DropoutSeason(dropout=1), DropoutSeason(dropout=4)),
            ),
        ),
        tvdb_id=361151,
    )
    _write_mkv(tmp_path, series.path, 4, 11, "Slug Eater")

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 30, "Slug Eater", air_date="2021-07-13"),
            SonarrEpisode(1, 1, "Pilot", air_date="2019-09-20"),
            SonarrEpisode(4, 11, "Slug Eater", air_date="2021-07-13"),
        ]

    run_dropout_check(_manifest(tmp_path, series), _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    missing_line = next(line for line in out.splitlines() if "S00E30" in line)
    assert "add to skip list" in missing_line
    assert "maybe" not in missing_line
    assert "S04E11" in missing_line


def test_check_suggests_fuzzy_dropout_title(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    season = DropoutSeason(dropout=26)
    series = DropoutSeries(
        name="Dimension 20's Adventuring Party",
        path="Dimension 20's Adventuring Party [tvdbid=391568]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/dimension-20-s-adventuring-party",
                seasons=(season,),
            ),
        ),
        tvdb_id=391568,
    )
    manifest = _manifest(tmp_path, series)
    _seed_listings(
        manifest,
        series,
        season,
        [
            {
                "url": "https://watch.dropout.tv/videos/cloudward-crew-confers",
                "title": "Cloudward Crew Confers",
                "dropout_episode": 3,
            }
        ],
    )

    def fetch(_tvdb_id: int):
        return "Dimension 20's Adventuring Party", [
            SonarrEpisode(0, 64, "The Cloudward Crew Confers"),
            SonarrEpisode(26, 1, "Pilot"),
        ]

    run_dropout_check(manifest, _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert "maybe season 26 E03" in out


def test_check_skip_remap_is_not_suggested(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    season = DropoutSeason(dropout=4, remap=(DropoutRemap(11, skip=True),))
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(url="https://watch.dropout.tv/game-changer", seasons=(season,)),
        ),
        tvdb_id=361151,
    )
    manifest = _manifest(tmp_path, series)
    _seed_listings(
        manifest,
        series,
        season,
        [
            {
                "url": "https://watch.dropout.tv/videos/cut-for-time",
                "title": "The Cloudward Crew Confers",
                "dropout_episode": 11,
            }
        ],
    )

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 64, "The Cloudward Crew Confers"),
            SonarrEpisode(4, 1, "Pilot"),
        ]

    run_dropout_check(manifest, _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert "S00E64" in out
    assert "season 4" not in out


def test_check_suggests_other_series_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    party_season = DropoutSeason(dropout=21)
    party = DropoutSeries(
        name="Dimension 20's Adventuring Party",
        path="Dimension 20's Adventuring Party [tvdbid=391568]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/dimension-20-s-adventuring-party",
                seasons=(party_season,),
            ),
        ),
        tvdb_id=391568,
    )
    d20 = DropoutSeries(
        name="Dimension 20",
        path="Dimension 20 [tvdbid=354216]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/dimension-20-the-complete-series",
                seasons=(DropoutSeason(dropout=26),),
            ),
        ),
        tvdb_id=354216,
    )
    manifest = _manifest(tmp_path, d20, party)
    _seed_listings(
        manifest,
        party,
        party_season,
        [
            {
                "url": "https://watch.dropout.tv/videos/the-cloudward-crew-confers",
                "title": "The Cloudward Crew Confers",
                "dropout_episode": 21,
            }
        ],
    )

    def fetch(tvdb_id: int):
        if tvdb_id == 354216:
            return "Dimension 20", [
                SonarrEpisode(0, 64, "The Cloudward Crew Confers"),
                SonarrEpisode(26, 1, "On High We Go"),
            ]
        return "Dimension 20's Adventuring Party", [
            SonarrEpisode(21, 21, "The Cloudward Crew Confers"),
        ]

    code = run_dropout_check(manifest, _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    assert code == 1
    missing_line = next(line for line in out.splitlines() if "S00E64" in line)
    assert "The Cloudward Crew Confers" in missing_line
    assert "season 21 E21" in missing_line
    assert "Adventuring Party" in missing_line
    assert "maybe season 21" not in missing_line
    assert "add to skip list" not in missing_line

    _write_mkv(tmp_path, party.path, 21, 21, "The Cloudward Crew Confers")
    run_dropout_check(manifest, _settings(tmp_path), fetch_fn=fetch)
    out = capsys.readouterr().out
    missing_line = next(line for line in out.splitlines() if "S00E64" in line)
    assert "maybe add to skip list" in missing_line
    assert "S21E21" in missing_line


def test_check_series_report_hints_are_dicts(tmp_path: Path) -> None:
    series = DropoutSeries(
        name="Game Changer",
        path="Game Changer [tvdbid=361151]",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/game-changer",
                seasons=(DropoutSeason(dropout=1), DropoutSeason(dropout=4)),
            ),
        ),
        tvdb_id=361151,
    )
    manifest = _manifest(tmp_path, series)
    _seed_listings(
        manifest,
        series,
        series.sources[0].seasons[0],
        [
            {
                "url": "https://watch.dropout.tv/videos/pilot",
                "title": "Pilot",
                "dropout_episode": 1,
            }
        ],
    )
    _write_mkv(tmp_path, series.path, 4, 11, "Slug Eater")

    def fetch(_tvdb_id: int):
        return "Game Changer", [
            SonarrEpisode(0, 30, "Slug Eater", air_date="2021-07-13"),
            SonarrEpisode(4, 11, "Slug Eater", air_date="2021-07-13"),
        ]

    report = check_series_report(
        manifest, _settings(tmp_path), "game-changer", fetch_fn=fetch
    )
    missing = report["missing"]
    assert missing
    hints = missing[0]["hints"]
    assert hints
    assert isinstance(hints[0], dict)
    assert "text" in hints[0]
    assert "kind" in hints[0]
    assert "sure" in hints[0]


def test_check_series_report_uses_series_when_web_slug_mismatches(tmp_path: Path) -> None:
    series = DropoutSeries(
        name="Dimension 20's Adventuring Party",
        path="AP",
        sources=(
            DropoutSource(
                url="https://watch.dropout.tv/ap",
                seasons=(DropoutSeason(dropout=1),),
            ),
        ),
        tvdb_id=391568,
    )
    manifest = _manifest(tmp_path, series)
    _seed_listings(
        manifest,
        series,
        series.sources[0].seasons[0],
        [
            {
                "url": "https://watch.dropout.tv/videos/pilot",
                "title": "Pilot",
                "dropout_episode": 1,
            }
        ],
    )

    def fetch(_tvdb_id: int):
        return "Dimension 20's Adventuring Party", [
            SonarrEpisode(1, 1, "Pilot"),
        ]

    with pytest.raises(ConfigError, match="series not found"):
        check_series_report(
            manifest,
            _settings(tmp_path),
            "dimension-20-adventuring-party",
            fetch_fn=fetch,
        )
    report = check_series_report(
        manifest,
        _settings(tmp_path),
        "dimension-20-adventuring-party",
        series=series,
        fetch_fn=fetch,
    )
    assert report["ok"] is True
