from pathlib import Path

from yt_dlp_emby.youtube_manifest import load_youtube_manifest, parse_youtube_manifest


def test_youtube_imports_and_empty_root_series(tmp_path: Path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    child = shows / "chan.yaml"
    child.write_text(
        """
series:
  - name: Example Channel
    path: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
        season: 1
        enabled: false
        skip:
          - vid123
""",
        encoding="utf-8",
    )
    root = tmp_path / "youtube.yaml"
    root.write_text(
        f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
imports:
  - shows/chan.yaml
series: []
""",
        encoding="utf-8",
    )
    manifest = load_youtube_manifest(root)
    assert len(manifest.series) == 1
    series = manifest.series[0]
    assert series.path == "Example Channel"
    assert series.playlists[0].enabled is False
    assert series.playlists[0].skip == ("vid123",)


def test_youtube_series_path_and_tvdb(tmp_path: Path) -> None:
    path = tmp_path / "youtube.yaml"
    path.write_text(
        f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Show
    path: Show Folder
    tvdb_id: 99
    playlists:
      - url: https://www.youtube.com/playlist?list=PLx
""",
        encoding="utf-8",
    )
    manifest = parse_youtube_manifest(
        __import__("yaml").safe_load(path.read_text(encoding="utf-8")),
        path,
        load_imports=False,
    )
    assert manifest.series[0].tvdb_id == 99
    assert manifest.series[0].path == "Show Folder"
