from pathlib import Path

import pytest

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.youtube_manifest import filter_youtube_manifest, load_youtube_manifest


def _write_manifest(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "youtube.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
        season: 1
      - url: https://www.youtube.com/playlist?list=PLbbbb
{extra}
""".format(lib=tmp_path / "lib", old=tmp_path / "old", extra=extra),
        encoding="utf-8",
    )
    return path


def test_load_youtube_manifest(tmp_path: Path) -> None:
    manifest = load_youtube_manifest(_write_manifest(tmp_path))
    series = manifest.series[0]
    assert series.name == "Example Channel"
    assert series.playlists[0].season == 1
    assert series.playlists[1].season is None
    assert series.playlists[1].url.endswith("PLbbbb")


def test_youtube_manifest_rejects_duplicate_urls(tmp_path: Path) -> None:
    path = tmp_path / "youtube.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
      - url: https://www.youtube.com/playlist?list=PLaaaa
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="Duplicate playlist URL"):
        load_youtube_manifest(path)


def test_youtube_manifest_rejects_bad_season(tmp_path: Path) -> None:
    path = tmp_path / "youtube.yaml"
    path.write_text(
        """
library: {lib}
old_dir: {old}
series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
        season: 0
""".format(lib=tmp_path / "lib", old=tmp_path / "old"),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="season"):
        load_youtube_manifest(path)


def test_youtube_manifest_rejects_invalid_yaml(tmp_path: Path) -> None:
    path = tmp_path / "youtube.yaml"
    path.write_text("library: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_youtube_manifest(path)


def test_filter_youtube_manifest_by_name(tmp_path: Path) -> None:
    extra = """
  - name: Other Show
    playlists:
      - url: https://www.youtube.com/playlist?list=PLcccc
"""
    manifest = load_youtube_manifest(_write_manifest(tmp_path, extra=extra))
    filtered = filter_youtube_manifest(manifest, series_names=["other"])
    assert len(filtered.series) == 1
    assert filtered.series[0].name == "Other Show"


def test_filter_youtube_manifest_by_url(tmp_path: Path) -> None:
    manifest = load_youtube_manifest(_write_manifest(tmp_path))
    filtered = filter_youtube_manifest(manifest, series_names=["PLbbbb"])
    assert len(filtered.series[0].playlists) == 1
    assert filtered.series[0].playlists[0].url.endswith("PLbbbb")


def test_filter_youtube_manifest_none_matched(tmp_path: Path) -> None:
    manifest = load_youtube_manifest(_write_manifest(tmp_path))
    with pytest.raises(ConfigError, match="No series matched"):
        filter_youtube_manifest(manifest, series_names=["nope"])


def test_youtube_manifest_allows_omitted_paths(tmp_path: Path) -> None:
    path = tmp_path / "youtube.yaml"
    path.write_text(
        """
series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
""",
        encoding="utf-8",
    )
    manifest = load_youtube_manifest(path)
    assert manifest.library is None
    assert manifest.old_dir is None
    assert manifest.staging is None
