"""Service-level planning and execution admission invariants.

The web foundation no longer exchanges CLI plan/event sidecars. These tests
exercise the same destination and selection boundary through the pure planner
and private executor adapter instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.server.services import (
    ProviderListing,
    current_configuration_revision,
    download_selected,
    library_snapshot,
    plan_series,
)


def test_planner_uses_explicit_destination_and_emits_selectable_action() -> None:
    listing = ProviderListing(
        platform="dropout",
        source_index=0,
        season_index=0,
        source_season=28,
        destination_season=27,
        episode=4,
        identity="dropout:source-a:season-28:episode-4",
        title="Special",
        url="https://watch.dropout.tv/special",
    )
    from yt_dlp_emby.server.services import LibrarySnapshot

    disk = LibrarySnapshot(
        status="ready",
        series_exists=True,
        episodes=(),
        episode_fingerprints=(),
        provider_index={},
        season_folders=("Season 27",),
        revision="disk-revision",
        scanned_at="now",
    )
    plan = plan_series(
        platform="dropout",
        slug="example",
        listings=[listing],
        disk=disk,
        config_revision="config-revision",
    )

    action = plan["actions"][0]
    assert action["action"] == "download"
    assert action["code"] == "S27E04"
    assert action["provider_identity"] == listing.identity
    assert action["id"]


def test_executor_rejects_changed_disk_before_any_provider_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = tmp_path / "library"
    show = library / "Example"
    (show / "Season 01").mkdir(parents=True)
    (tmp_path / "dropout.yaml").write_text(
        f"library: {library}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: Example\n    path: Example\n"
        "    url: https://watch.dropout.tv/example\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    revision = current_configuration_revision(tmp_path, {}, "dropout", "example")
    disk = library_snapshot(library, "Example")
    listing = ProviderListing(
        platform="dropout",
        source_index=0,
        season_index=0,
        source_season=1,
        destination_season=1,
        episode=1,
        identity="dropout:source-a:season-1:episode-1",
        title="Pilot",
        url="https://watch.dropout.tv/example/videos/pilot",
    )
    plan = plan_series(
        platform="dropout",
        slug="example",
        listings=[listing],
        disk=disk,
        config_revision=revision,
    )
    selected = plan["actions"][0]
    cached_view = {
        "target": {"platform": "dropout", "slug": "example"},
        "config_revision": revision,
        "disk": disk.to_dict(),
    }

    # A new file changes the fingerprint after the user selected the action.
    (show / "Season 01" / "Example - S01E99 - Concurrent.mkv").write_bytes(b"changed")
    monkeypatch.setattr(
        "yt_dlp_emby.dropout.run_dropout",
        lambda *_args, **_kwargs: pytest.fail("executor reached before stale-plan check"),
    )
    context = {
        "plan_id": plan["plan_id"],
        "selected_actions": [selected],
        "cached_views": [{"platform": "dropout", "slug": "example", "view": cached_view}],
    }

    with pytest.raises(ConfigError, match="library changed"):
        download_selected(
            tmp_path,
            {},
            plan["plan_id"],
            [selected["id"]],
            operation_context=context,
        )
    assert not list(library.rglob("*.part"))
