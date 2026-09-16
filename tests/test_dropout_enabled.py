from pathlib import Path

from yt_dlp_emby.dropout_manifest import load_dropout_manifest


def test_dropout_season_enabled_false(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Test
    path: Test
    url: https://watch.dropout.tv/test
    seasons:
      - dropout: 1
        enabled: false
      - dropout: 2
""",
        encoding="utf-8",
    )
    manifest = load_dropout_manifest(path)
    seasons = manifest.series[0].sources[0].seasons
    assert seasons[0].enabled is False
    assert seasons[1].enabled is True
