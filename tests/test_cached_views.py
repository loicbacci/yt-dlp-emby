"""Cached plans replace event sidecars and independent refresh stamps."""

from dataclasses import asdict
from pathlib import Path

import pytest
import yaml

from yt_dlp_emby.server.job_store import JobStore
from yt_dlp_emby.server.services import (
    ProviderListing,
    current_configuration_revision,
    plan_variant,
)
from yt_dlp_emby.server.views import executable_selection, latest_plan, latest_queue, series_detail


@pytest.fixture
def cached_library(tmp_path: Path):
    shows = tmp_path / "shows"
    shows.mkdir()
    (tmp_path / "dropout.yaml").write_text(
        yaml.safe_dump(
            {"library": str(tmp_path / "library"), "imports": ["shows/a.yaml", "shows/b.yaml"]}
        )
    )
    for slug, name in (("a", "Dimension 20's Adventuring Party"), ("b", "Other")):
        (shows / f"{slug}.yaml").write_text(
            yaml.safe_dump(
                {
                    "series": [
                        {
                            "name": name,
                            "path": name,
                            "url": f"https://watch.dropout.tv/{slug}",
                            "seasons": [{"dropout": 28, "to_season": 0}],
                        }
                    ]
                }
            )
        )
    store = JobStore(tmp_path / "jobs.sqlite3")
    yield tmp_path, store
    store.close()


def _publish(data: Path, store: JobStore, slug: str, *, exists=True, unavailable=False):
    listings = [
        ProviderListing(
            platform="dropout",
            source_index=0,
            season_index=0,
            source_season=28,
            destination_season=0,
            episode=12,
            mapped_episode=12,
            identity=f"source-{slug}:28:12",
            title="Cut",
            url="https://watch.dropout.tv/videos/cut",
        )
    ]
    view = {
        "target": {"platform": "dropout", "slug": slug},
        "config_revision": current_configuration_revision(data, {}, "dropout", slug),
        "provider_listings": [asdict(row) for row in listings],
        "disk": {
            "status": "unavailable" if unavailable else "ready",
            "series_exists": None if unavailable else exists,
            "episodes": None if unavailable else [[0, 12]],
            "episode_fingerprints": [],
            "revision": "disk",
            "scanned_at": "2026-01-01T00:00:00Z",
            "error": "NAS offline" if unavailable else None,
        },
        "stale": unavailable,
    }
    plan = plan_variant(view)
    store.put_view(
        "dropout",
        slug,
        {"view": view},
        plan,
        plan["revision"],
        "stale" if unavailable else "ready",
        "attempt",
        "success",
        "NAS offline" if unavailable else None,
    )
    return view


def test_cached_plan_uses_import_file_slug_and_specials(cached_library) -> None:
    data, store = cached_library
    _publish(data, store, "a")
    plan = latest_plan(data, {}, store)
    row = plan["sources"]["dropout"]["items"][0]
    assert row["slug"] == "a"
    assert row["code"] == "S00E12"
    assert row["action"] == "present"
    assert row["folder"] == "Specials"
    assert plan["sources"]["dropout"]["seasons"][0]["download"] == 0


def test_derived_queue_contains_only_missing_episodes(cached_library) -> None:
    data, store = cached_library
    view = _publish(data, store, "a")
    view["disk"]["episodes"] = []
    plan = plan_variant(view, create=True)
    store.put_view("dropout", "a", {"view": view}, plan, plan["revision"], "ready", "now", "now")

    queue = latest_queue(data, {}, store)
    rows = queue["sources"]["dropout"]["items"]
    assert len(rows) == 1
    assert rows[0]["action"] == "download"


def test_force_changes_cached_plan_revision_and_only_existing_action(cached_library) -> None:
    data, store = cached_library
    _publish(data, store, "a")
    ordinary = latest_plan(data, {}, store)
    forced = latest_plan(data, {}, store, force=True)
    assert ordinary["plan_id"] != forced["plan_id"]
    assert forced["sources"]["dropout"]["items"][0]["action"] == "replace"
    ident = forced["sources"]["dropout"]["items"][0]["id"]
    with pytest.raises(ValueError, match="PLAN_STALE"):
        executable_selection(data, {}, store, forced["plan_id"], [ident])
    selection = executable_selection(data, {}, store, forced["plan_id"], [ident], force=True)
    assert len(selection["cached_views"]) == 1
    assert selection["selected_actions"][0]["provider_identity"] == "source-a:28:12"


def test_unavailable_library_retains_unknown_counts_and_blocks_force(cached_library) -> None:
    data, store = cached_library
    _publish(data, store, "a", unavailable=True)
    plan = latest_plan(data, {}, store, force=True, create=True)
    assert plan["readiness"] == "unavailable"
    assert plan["sources"]["dropout"]["items"][0]["action"] == "blocked"
    detail = series_detail(data, {}, store, "dropout", "a")
    assert detail["missing_count"] is None
    assert detail["complete"] is False
    assert detail["last_success_at"] == "success"


def test_success_timestamps_are_per_target_and_failure_keeps_good_snapshot(cached_library) -> None:
    data, store = cached_library
    first = _publish(data, store, "a")
    _publish(data, store, "b")
    store.record_view_attempt("dropout", "a", "provider failed")
    failed = store.get_view("dropout", "a")
    assert failed["inputs"]["view"] == first
    assert failed["last_success_at"] == "success"
    assert failed["last_attempt_at"] != "attempt"
    other = store.get_view("dropout", "b")
    assert other["freshness"] == "ready"
    assert other["last_attempt_at"] == "attempt"
    assert series_detail(data, {}, store, "dropout", "a")["refreshed"]["listings"] == "success"


def test_views_survive_job_history_retention_and_database_reopen(cached_library) -> None:
    data, store = cached_library
    _publish(data, store, "a")
    before = latest_plan(data, {}, store)
    store.create("old-job", "refresh", {"kind": "refresh", "items": []})
    store.update("old-job", status="succeeded")
    store.retain(count=0)
    assert store.get("old-job") is None
    reopened = JobStore(data / "jobs.sqlite3")
    try:
        assert latest_plan(data, {}, reopened)["plan_id"] == before["plan_id"]
    finally:
        reopened.close()
