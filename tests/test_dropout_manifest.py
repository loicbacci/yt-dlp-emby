import json
from pathlib import Path

import pytest

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.dropout_manifest import (
    filter_dropout_manifest,
    load_dropout_manifest,
    season_page_url,
)


def _write_root(tmp_path: Path, body: str, *, name: str = "dropout.yaml") -> Path:
    path = tmp_path / name
    path.write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\n{body}",
        encoding="utf-8",
    )
    return path


def test_shorthand_url_seasons_is_one_source(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 28
        to_season: 27
""",
    )
    series = load_dropout_manifest(path).series[0]
    assert len(series.sources) == 1
    source = series.sources[0]
    assert source.url == "https://watch.dropout.tv/dimension-20-the-complete-series"
    assert season_page_url(source, source.seasons[0]).endswith("/season:28")


def test_urls_two_catalogs(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    urls:
      - url: https://watch.dropout.tv/dimension-20-the-complete-series
        seasons:
          - dropout: 28
            to_season: 27
      - url: https://watch.dropout.tv/dimension-20-live-complete-collection
        seasons:
          - dropout: 1
            remap:
              - dropout_episode: 1
                to_season: 0
                to_episode: 48
""",
    )
    sources = load_dropout_manifest(path).series[0].sources
    assert len(sources) == 2
    assert sources[0].url.endswith("dimension-20-the-complete-series")
    assert sources[1].url.endswith("dimension-20-live-complete-collection")
    assert season_page_url(sources[0], sources[0].seasons[0]).endswith("/season:28")
    assert season_page_url(sources[1], sources[1].seasons[0]).endswith("/season:1")


def test_urls_rejects_mixed_with_series_url(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    urls:
      - url: https://watch.dropout.tv/dimension-20-live-complete-collection
        seasons:
          - dropout: 1
""",
    )
    with pytest.raises(ConfigError, match="urls"):
        load_dropout_manifest(path)


def test_urls_rejects_mixed_with_series_seasons(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    seasons:
      - dropout: 1
    urls:
      - url: https://watch.dropout.tv/dimension-20-the-complete-series
        seasons:
          - dropout: 1
""",
    )
    with pytest.raises(ConfigError, match="urls"):
        load_dropout_manifest(path)


def test_urls_empty_list_allowed_for_new_series(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    urls: []
""",
    )
    manifest = load_dropout_manifest(path)
    assert manifest.series[0].sources == ()


def test_urls_item_requires_seasons(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    urls:
      - url: https://watch.dropout.tv/dimension-20-the-complete-series
""",
    )
    with pytest.raises(ConfigError, match="seasons"):
        load_dropout_manifest(path)


def test_tvdb_id_and_skip_parse(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Game Changer
    path: Game Changer [tvdbid=361151]
    tvdb_id: 361151
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
    tvdb_skip:
      - season: 0
        episodes: [12, 13]
""",
    )
    series = load_dropout_manifest(path).series[0]
    assert series.tvdb_id == 361151
    assert (0, 12) in series.tvdb_skip
    assert (0, 13) in series.tvdb_skip


def test_tvdb_skip_rejects_empty_episodes(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Game Changer
    path: Game Changer [tvdbid=361151]
    tvdb_id: 361151
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
    tvdb_skip:
      - season: 0
        episodes: []
""",
    )
    with pytest.raises(ConfigError, match="episodes"):
        load_dropout_manifest(path)


def test_tvdb_id_rejects_non_int(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Game Changer
    path: Game Changer [tvdbid=361151]
    tvdb_id: "361151"
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
    )
    with pytest.raises(ConfigError, match="tvdb_id"):
        load_dropout_manifest(path)


def test_imports_optional_current_file_still_loads(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
series:
  - name: Game Changer
    path: Game Changer [tvdbid=369988]
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
    )
    manifest = load_dropout_manifest(path)
    assert len(manifest.series) == 1
    assert manifest.series[0].name == "Game Changer"


def test_imports_only_no_root_series(tmp_path: Path) -> None:
    child = tmp_path / "shows" / "game-changer.yaml"
    child.parent.mkdir()
    child.write_text(
        """
series:
  - name: Game Changer
    path: Game Changer [tvdbid=369988]
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/game-changer.yaml
""",
    )
    manifest = load_dropout_manifest(path)
    assert [series.name for series in manifest.series] == ["Game Changer"]


def test_imports_then_root_series_concatenated(tmp_path: Path) -> None:
    child = tmp_path / "shows" / "a.yaml"
    child.parent.mkdir()
    child.write_text(
        """
series:
  - name: Show A
    path: Show A [tvdbid=1]
    url: https://watch.dropout.tv/show-a
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/a.yaml
series:
  - name: Show B
    path: Show B [tvdbid=2]
    url: https://watch.dropout.tv/show-b
    seasons:
      - dropout: 1
""",
    )
    names = [series.name for series in load_dropout_manifest(path).series]
    assert names == ["Show A", "Show B"]


def test_same_path_across_files_merges_sources(tmp_path: Path) -> None:
    child = tmp_path / "shows" / "d20.yaml"
    child.parent.mkdir()
    child.write_text(
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/d20.yaml
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-live-complete-collection
    seasons:
      - dropout: 1
""",
    )
    series = load_dropout_manifest(path).series
    assert len(series) == 1
    urls = [source.url for source in series[0].sources]
    assert urls == [
        "https://watch.dropout.tv/dimension-20-the-complete-series",
        "https://watch.dropout.tv/dimension-20-live-complete-collection",
    ]


def test_same_path_unions_tvdb_skip_and_inherits_tvdb_id(tmp_path: Path) -> None:
    child = tmp_path / "shows" / "d20.yaml"
    child.parent.mkdir()
    child.write_text(
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    tvdb_skip:
      - season: 0
        episodes: [12]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/d20.yaml
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    tvdb_id: 354216
    tvdb_skip:
      - season: 0
        episodes: [13]
    url: https://watch.dropout.tv/dimension-20-live-complete-collection
    seasons:
      - dropout: 1
""",
    )
    series = load_dropout_manifest(path).series[0]
    assert series.tvdb_id == 354216
    assert series.tvdb_skip == frozenset({(0, 12), (0, 13)})


def test_same_path_conflicting_tvdb_id_errors(tmp_path: Path) -> None:
    child = tmp_path / "shows" / "d20.yaml"
    child.parent.mkdir()
    child.write_text(
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    tvdb_id: 354216
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/d20.yaml
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    tvdb_id: 999999
    url: https://watch.dropout.tv/dimension-20-live-complete-collection
    seasons:
      - dropout: 1
""",
    )
    with pytest.raises(ConfigError, match="tvdb_id"):
        load_dropout_manifest(path)


def test_import_child_rejects_library(tmp_path: Path) -> None:
    child = tmp_path / "shows" / "game-changer.yaml"
    child.parent.mkdir()
    child.write_text(
        """
library: /somewhere
series:
  - name: Game Changer
    path: Game Changer [tvdbid=369988]
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/game-changer.yaml
""",
    )
    with pytest.raises(ConfigError, match="library"):
        load_dropout_manifest(path)


def test_dropout_manifest_allows_omitted_paths(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
series:
  - name: Game Changer
    path: Game Changer
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    manifest = load_dropout_manifest(path)
    assert manifest.library is None
    assert manifest.old_dir is None


def test_import_child_rejects_nested_imports(tmp_path: Path) -> None:
    nested = tmp_path / "shows" / "nested.yaml"
    nested.parent.mkdir()
    nested.write_text("series: []\n", encoding="utf-8")
    child = tmp_path / "shows" / "game-changer.yaml"
    child.write_text(
        """
imports:
  - shows/nested.yaml
series:
  - name: Game Changer
    path: Game Changer [tvdbid=369988]
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/game-changer.yaml
""",
    )
    with pytest.raises(ConfigError, match="imports"):
        load_dropout_manifest(path)


def test_import_missing_file_errors(tmp_path: Path) -> None:
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/missing.yaml
""",
    )
    with pytest.raises(ConfigError, match="not found"):
        load_dropout_manifest(path)


def test_import_relative_to_manifest_dir(tmp_path: Path) -> None:
    nested = tmp_path / "config"
    nested.mkdir()
    child = tmp_path / "shows" / "game-changer.yaml"
    child.parent.mkdir()
    child.write_text(
        """
series:
  - name: Game Changer
    path: Game Changer [tvdbid=369988]
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        nested,
        """
imports:
  - ../shows/game-changer.yaml
""",
    )
    manifest = load_dropout_manifest(path)
    assert manifest.series[0].name == "Game Changer"


def test_filter_series_matches_imported_name(tmp_path: Path) -> None:
    child = tmp_path / "shows" / "game-changer.yaml"
    child.parent.mkdir()
    child.write_text(
        """
series:
  - name: Game Changer
    path: Game Changer [tvdbid=369988]
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    path = _write_root(
        tmp_path,
        """
imports:
  - shows/game-changer.yaml
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    url: https://watch.dropout.tv/dimension-20-the-complete-series
    seasons:
      - dropout: 1
""",
    )
    filtered = filter_dropout_manifest(
        load_dropout_manifest(path),
        series_names=["Game Changer"],
    )
    assert [series.name for series in filtered.series] == ["Game Changer"]


def test_filter_url_only_season_by_to_season(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
series:
  - name: Show
    path: Show
    url: https://watch.dropout.tv/x
    seasons:
      - url: https://watch.dropout.tv/x/season:special
        to_season: 0
      - dropout: 5
        to_season: 12
""",
        encoding="utf-8",
    )
    filtered = filter_dropout_manifest(load_dropout_manifest(path), dropout_seasons=[0])
    seasons = [season for source in filtered.series[0].sources for season in source.seasons]
    assert len(seasons) == 1
    assert seasons[0].to_season == 0
    assert seasons[0].dropout is None


def test_series_path_rejects_parent_dir(tmp_path: Path) -> None:
    path = tmp_path / "dropout.yaml"
    path.write_text(
        """
series:
  - name: Evil
    path: ../outside
    url: https://watch.dropout.tv/x
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="inside the library"):
        load_dropout_manifest(path)


def test_schema_files_are_json() -> None:
    for name in ("dropout.schema.json", "dropout-series.schema.json"):
        json.loads(
            (Path(__file__).resolve().parent.parent / "schemas" / name).read_text(encoding="utf-8")
        )


def test_examples_declare_yaml_language_server_schema() -> None:
    root = Path(__file__).resolve().parent.parent
    for path in (
        root / "dropout.yaml.example",
        root / "src/yt_dlp_emby/server/examples/dropout.yaml.example",
    ):
        first = path.read_text(encoding="utf-8").splitlines()[0]
        assert first.startswith("# yaml-language-server: $schema=")
        assert "dropout.schema.json" in first
    fragment = root / "src/yt_dlp_emby/server/examples/shows/dimension-20.yaml.example"
    first = fragment.read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith("# yaml-language-server: $schema=")
    assert "dropout-series.schema.json" in first
