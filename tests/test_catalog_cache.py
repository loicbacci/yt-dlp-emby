import json
from datetime import datetime, timedelta, timezone

from yt_dlp_emby.server.catalog_cache import patch_inventory, write_snapshot
from yt_dlp_emby.server.views import cache_is_stale


def test_catalog_cache_snapshot_persists_and_patches_inventory(tmp_path):
    view = {
        "config_revision": "config-a",
        "source_signature": "source-a",
        "context_signature": "context-a",
        "provider_listings": [{"identity": "video-a"}],
        "disk": {"status": "ready", "episodes": [[1, 1]], "series_exists": True},
        "cache_times": {
            "listings": "2026-10-01T00:00:00+00:00",
            "disk": "2026-10-01T00:00:00+00:00",
        },
    }

    write_snapshot(tmp_path, "youtube", "sample-show", view)
    cache_path = next((tmp_path / "cache" / "youtube").glob("*.json"))
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert cached["provider_listings"] == view["provider_listings"]
    assert cached["fingerprint"]

    patch_inventory(tmp_path, "youtube", "sample-show", 1, 2)
    patched = json.loads(cache_path.read_text(encoding="utf-8"))
    assert patched["disk"]["episodes"] == [[1, 1], [1, 2]]
    assert patched["view"]["disk"]["episodes"] == [[1, 1], [1, 2]]


def test_cache_ttl_is_24_hours():
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    record = {
        "freshness": "ready",
        "inputs": {"view": {"cache_times": {"listings": (now - timedelta(hours=23)).isoformat()}}},
        "last_success_at": (now - timedelta(hours=23)).isoformat(),
    }
    assert not cache_is_stale(record, now=now)
    record["inputs"]["view"]["cache_times"]["listings"] = (now - timedelta(hours=25)).isoformat()
    assert cache_is_stale(record, now=now)
