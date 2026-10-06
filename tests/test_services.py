from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.server.services import (
    LibrarySnapshot,
    ProviderListing,
    apply_refresh_updates,
    current_configuration_revision,
    library_snapshot,
    load_config_snapshot,
    plan_series,
    plan_variant,
    verify_completed_actions,
)


def _listing() -> ProviderListing:
    return ProviderListing(
        platform="dropout",
        source_index=0,
        season_index=0,
        source_season=28,
        destination_season=27,
        episode=4,
        identity="dropout:source-a:season-28:episode-4",
        title="Special",
        url="https://watch.dropout.tv/special",
        mapped_episode=9,
        mapped_title="Custom episode title",
    )


def test_config_snapshot_honors_selected_config_path_without_creating_defaults(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "settings.toml"
    selected.write_text('[fallback]\nlibrary = "/library"\n', encoding="utf-8")
    default = tmp_path / "config.toml"
    snapshot = load_config_snapshot(tmp_path, {"YT_DLP_EMBY_CONFIG": str(selected)})

    assert snapshot.path == str(selected)
    assert snapshot.values == {"library": "/library"}
    assert not default.exists()


def test_configuration_revision_is_target_semantic_but_tracks_effective_globals(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "dropout.yaml"
    manifest.write_text(
        f"""library: {tmp_path / "library"}
old_dir: {tmp_path / "old"}
series:
  - name: Alpha
    path: Alpha
    url: https://watch.dropout.tv/alpha
    seasons:
      - dropout: 1
        to_season: 1
  - name: Beta
    path: Beta
    url: https://watch.dropout.tv/beta
    seasons:
      - dropout: 1
        to_season: 1
""",
        encoding="utf-8",
    )
    env: dict[str, str] = {}
    alpha = current_configuration_revision(tmp_path, env, "dropout", "alpha")

    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("/beta", "/beta-updated"),
        encoding="utf-8",
    )
    assert current_configuration_revision(tmp_path, env, "dropout", "alpha") == alpha

    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("to_season: 1", "to_season: 2", 1),
        encoding="utf-8",
    )
    assert current_configuration_revision(tmp_path, env, "dropout", "alpha") != alpha

    changed_global = manifest.read_text(encoding="utf-8").replace(
        str(tmp_path / "library"), str(tmp_path / "other-library")
    )
    manifest.write_text(changed_global, encoding="utf-8")
    assert current_configuration_revision(tmp_path, env, "dropout", "alpha") != alpha


def test_library_snapshot_distinguishes_missing_show_from_unavailable_library(
    tmp_path: Path,
) -> None:
    library = tmp_path / "library"
    library.mkdir()
    absent_show = library_snapshot(library, "A Show")
    unavailable = library_snapshot(tmp_path / "missing-library", "A Show")

    assert absent_show.status == "ready"
    assert absent_show.series_exists is False
    assert absent_show.episodes == ()
    assert unavailable.status == "unavailable"
    assert unavailable.series_exists is None
    assert unavailable.episodes is None


def test_library_snapshot_fingerprints_files_and_guards_changed_mount(tmp_path: Path) -> None:
    library = tmp_path / "library"
    episode = library / "Show" / "Season 01" / "Show - S27E09 - Special.mkv"
    episode.parent.mkdir(parents=True)
    episode.write_bytes(b"one")
    first = library_snapshot(library, "Show")

    assert first.status == "ready"
    assert first.episodes == ((27, 9),)
    assert first.episode_fingerprints == ((27, 9, 3, episode.stat().st_mtime_ns),)

    episode.write_bytes(b"changed-size")
    second = library_snapshot(library, "Show")
    assert second.revision != first.revision
    changed = library_snapshot(library, "Show", expected_mount_identity="old-mount")
    assert changed.status == "unavailable"
    assert changed.series_exists is None


def test_planner_blocks_unknown_disk_and_hashes_custom_mapping() -> None:
    row = _listing()
    unavailable = LibrarySnapshot(
        status="unavailable",
        series_exists=None,
        episodes=None,
        episode_fingerprints=None,
        provider_index=None,
        season_folders=(),
        revision=None,
        scanned_at="now",
        error="offline",
    )
    blocked = plan_series(
        platform="dropout",
        slug="example",
        listings=[row],
        disk=unavailable,
        config_revision="cfg",
        options={},
    )
    assert blocked["readiness"] == "blocked"
    assert blocked["actions"][0]["action"] == "blocked"
    assert blocked["actions"][0]["blocked_reason"] == "library is unavailable"

    ready = LibrarySnapshot(
        status="ready",
        series_exists=True,
        episodes=(),
        episode_fingerprints=(),
        provider_index={},
        season_folders=(),
        revision="disk-1",
        scanned_at="now",
    )
    mapped = plan_series(
        platform="dropout",
        slug="example",
        listings=[row],
        disk=ready,
        config_revision="cfg",
        options={},
    )
    assert mapped["actions"][0]["code"] == "S27E09"
    assert mapped["actions"][0]["provider_identity"] == row.identity
    assert mapped["actions"][0]["title"] == "Custom episode title"
    assert mapped["plan_id"] != blocked["plan_id"]


def test_cached_option_variants_show_force_and_create_without_rescanning() -> None:
    row = _listing()
    existing = LibrarySnapshot(
        status="ready",
        series_exists=True,
        episodes=((27, 9),),
        episode_fingerprints=((27, 9, 3, 10),),
        provider_index={},
        season_folders=("Season 27",),
        revision="disk",
        scanned_at="now",
    )
    view = {
        "target": {"platform": "dropout", "slug": "example"},
        "config_revision": "cfg",
        "disk": existing.to_dict(),
        "provider_listings": [row.__dict__],
    }

    ordinary = plan_variant(view)
    force = plan_variant(view, force=True)
    assert ordinary["actions"][0]["action"] == "present"
    assert force["actions"][0]["action"] == "replace"
    assert force["plan_id"] != ordinary["plan_id"]

    absent = LibrarySnapshot(
        status="ready",
        series_exists=False,
        episodes=(),
        episode_fingerprints=(),
        provider_index={},
        season_folders=(),
        revision="disk-empty",
        scanned_at="now",
    )
    view["disk"] = absent.to_dict()
    requires_create = plan_variant(view)
    created = plan_variant(view, create=True)
    assert requires_create["readiness"] == "create_required"
    assert requires_create["actions"][0]["action"] == "blocked"
    assert created["actions"][0]["action"] == "download"
    assert created["actions"][0]["create_folder"] is True
    assert created["plan_id"] != requires_create["plan_id"]


def test_youtube_pure_sync_plan_keeps_remove_and_add_selection_distinct() -> None:
    rows = [
        ProviderListing(
            platform="youtube",
            source_index=0,
            season_index=0,
            source_season=1,
            destination_season=1,
            episode=1,
            identity="new-video",
            title="New title",
            url="https://www.youtube.com/watch?v=new-video",
            playlist_id="PL-one",
            playlist_title="Season 1",
            channel="Example",
        )
    ]
    disk = LibrarySnapshot(
        status="ready",
        series_exists=True,
        episodes=((1, 1),),
        episode_fingerprints=((1, 1, 3, 20),),
        provider_index={
            "playlists": {
                "PL-one": {
                    "season": 1,
                    "title": "Season 1",
                    "episodes": {
                        "old-video": {
                            "video_id": "old-video",
                            "episode": 1,
                            "title": "Old title",
                            "basename": "Example - S01E01 - Old title",
                            "season": 1,
                        }
                    },
                }
            }
        },
        season_folders=("Season 01",),
        revision="disk",
        scanned_at="now",
    )
    plan = plan_series(
        platform="youtube",
        slug="example",
        listings=rows,
        disk=disk,
        config_revision="cfg",
    )
    actions = plan["actions"]
    assert {row["action"] for row in actions} == {"remove", "download"}
    assert len({row["id"] for row in actions}) == 2
    download = next(row for row in actions if row["action"] == "download")
    removal = next(row for row in actions if row["action"] == "remove")
    assert download["dependencies"] == [removal["id"]]
    assert download["folder"] == "Season 01"


def test_youtube_skip_does_not_turn_existing_index_item_into_remove() -> None:
    skipped = ProviderListing(
        "youtube",
        0,
        0,
        1,
        1,
        1,
        "old-video",
        "Old title",
        "https://www.youtube.com/watch?v=old-video",
        skipped=True,
        playlist_id="PL-one",
        channel="Example",
    )
    disk = LibrarySnapshot(
        status="ready",
        series_exists=True,
        episodes=((1, 1),),
        episode_fingerprints=((1, 1, 3, 20),),
        provider_index={
            "playlists": {
                "PL-one": {
                    "season": 1,
                    "episodes": {"old-video": {"episode": 1, "title": "Old", "basename": "Old"}},
                }
            }
        },
        season_folders=(),
        revision="disk",
        scanned_at="now",
    )
    plan = plan_series(
        platform="youtube",
        slug="example",
        listings=[skipped],
        disk=disk,
        config_revision="cfg",
    )
    assert plan["actions"] == []


def test_refresh_config_update_is_compare_and_swap_and_preserves_yaml_comments(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dropout.yaml"
    original = (
        "# library comment\nlibrary: /media\nseries:\n  - name: Example\n"
        "    path: Example\n    url: https://watch.dropout.tv/example\n"
        "    seasons:\n      - dropout: 28 # custom source season\n"
        "        to_season: 27 # custom mapping\n"
        '        title: "A quoted title"\n'
    )
    path.write_text(original, encoding="utf-8")
    update = {
        "platform": "dropout",
        "slug": "example",
        "file": "dropout.yaml",
        "expected_hash": hashlib.sha256(original.encode()).hexdigest(),
        "inline": True,
        "index": 0,
        "series": {
            "name": "Example",
            "path": "Example",
            "url": "https://watch.dropout.tv/example",
            "seasons": [
                {
                    "dropout": 28,
                    "url": "https://watch.dropout.tv/example-season-28",
                    "to_season": 27,
                    "title": "A quoted title",
                },
                {
                    "dropout": 29,
                    "url": "https://watch.dropout.tv/example-season-29",
                    "to_season": 29,
                    "enabled": False,
                },
            ],
        },
    }

    apply_refresh_updates(tmp_path, update)
    saved = path.read_text(encoding="utf-8")
    assert "# library comment" in saved
    assert "# custom source season" in saved
    assert "# custom mapping" in saved
    assert 'title: "A quoted title"' in saved
    assert "dropout: 29" in saved

    with pytest.raises(ConfigError, match="manifest changed"):
        apply_refresh_updates(tmp_path, update)


def test_retry_verification_requires_new_file_for_download(tmp_path: Path) -> None:
    library = tmp_path / "library"
    show = library / "Example"
    (show / "Season 01").mkdir(parents=True)
    (tmp_path / "dropout.yaml").write_text(
        f"library: {library}\nseries:\n  - name: Example\n    path: Example\n"
        "    url: https://watch.dropout.tv/example\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    config_revision = current_configuration_revision(tmp_path, {}, "dropout", "example")
    before = library_snapshot(library, "Example")
    episode = show / "Season 01" / "Example - S01E01 - Pilot.mkv"
    episode.write_bytes(b"completed download")
    rows = [
        {
            "id": "act_download",
            "platform": "dropout",
            "slug": "example",
            "action": "download",
            "dest_season": 1,
            "dest_episode": 1,
        }
    ]
    cached_views = [
        {
            "platform": "dropout",
            "slug": "example",
            "view": {
                "config_revision": config_revision,
                "disk": before.to_dict(),
            },
        }
    ]

    assert verify_completed_actions(tmp_path, {}, rows, cached_views) == {"act_download"}


def test_retry_verification_rejects_unchanged_replacement_fingerprint(
    tmp_path: Path,
) -> None:
    library = tmp_path / "library"
    show = library / "Example"
    season = show / "Season 01"
    season.mkdir(parents=True)
    episode = season / "Example - S01E01 - Pilot.mkv"
    episode.write_bytes(b"before")
    (tmp_path / "dropout.yaml").write_text(
        f"library: {library}\nseries:\n  - name: Example\n    path: Example\n"
        "    url: https://watch.dropout.tv/example\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    config_revision = current_configuration_revision(tmp_path, {}, "dropout", "example")
    before = library_snapshot(library, "Example")
    rows = [
        {
            "id": "act_replace",
            "platform": "dropout",
            "slug": "example",
            "action": "replace",
            "dest_season": 1,
            "dest_episode": 1,
        }
    ]
    cached_views = [
        {
            "platform": "dropout",
            "slug": "example",
            "view": {
                "config_revision": config_revision,
                "disk": before.to_dict(),
            },
        }
    ]

    assert verify_completed_actions(tmp_path, {}, rows, cached_views) == set()
    episode.write_bytes(b"replacement")
    assert verify_completed_actions(tmp_path, {}, rows, cached_views) == {"act_replace"}
