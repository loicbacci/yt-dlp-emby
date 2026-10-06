"""Exercise the actual private worker without network providers or mocked transport."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app


def _wait(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] not in {"queued", "running", "stopping"}:
            return job
        time.sleep(0.03)
    raise AssertionError("private worker did not finish")


def _empty_show(data: Path, library: Path) -> None:
    (data / "youtube.yaml").write_text(
        f"library: {library}\nold_dir: {data / 'old'}\n"
        "series:\n  - name: Empty\n    path: Empty\n    playlists: []\n"
    )


def test_real_refresh_worker_publishes_cached_plan_without_creating_media(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    _empty_show(tmp_path, library)
    with TestClient(create_app(data_dir=tmp_path, environ={})) as client:
        assert client.post("/api/setup", json={"password": "test-password"}).status_code == 200
        started = client.post(
            "/api/jobs",
            json={"kind": "refresh", "items": [{"platform": "youtube", "slug": "empty"}]},
        )
        assert started.status_code == 202, started.text
        assert started.json()["status"] == "queued"
        job = _wait(client, started.json()["job_id"])
        assert job["status"] == "succeeded", job
        assert job["result"]["ok"] is True
        plan = client.get("/api/plans/latest")
        assert plan.status_code == 200, plan.text
        assert plan.json()["plan_id"]
        assert "sources" in plan.json()
        assert not (library / "Empty").exists()
        assert not (tmp_path / "old").exists()
        for legacy in ("plan.json", "events.jsonl", "download-only.json"):
            assert not (tmp_path / legacy).exists()


def test_unavailable_root_refresh_never_creates_a_replacement_library(tmp_path: Path) -> None:
    library = tmp_path / "unmounted" / "library"
    _empty_show(tmp_path, library)
    with TestClient(create_app(data_dir=tmp_path, environ={})) as client:
        assert client.post("/api/setup", json={"password": "test-password"}).status_code == 200
        response = client.post(
            "/api/jobs",
            json={"kind": "refresh", "items": [{"platform": "youtube", "slug": "empty"}]},
        )
        assert response.status_code == 202, response.text
        job = _wait(client, response.json()["job_id"])
        assert job["status"] == "failed", job
        assert not library.exists()
        assert not (tmp_path / "old").exists()
        failed = job["result"]["results"][0]
        assert failed["error"]
        assert "view" in failed, failed
        assert failed["view"]["disk"]["episodes"] is None


def test_cached_gets_do_not_create_or_scan_missing_library(tmp_path: Path, monkeypatch) -> None:
    library = tmp_path / "unmounted" / "library"
    _empty_show(tmp_path, library)
    scans = []
    monkeypatch.setattr(
        "yt_dlp_emby.server.services.library_snapshot",
        lambda *args, **kwargs: scans.append(args) or set(),
    )
    with TestClient(create_app(data_dir=tmp_path, environ={})) as client:
        assert client.post("/api/setup", json={"password": "test-password"}).status_code == 200
        for path in ("/api/series", "/api/series/youtube/empty", "/api/series/youtube/empty/disk"):
            assert client.get(path).status_code == 200
        assert client.get("/api/jobs").json()["active"] is None
        assert not scans, "GET views must use cached disk state rather than scan the NAS"
        assert not library.exists()


def test_private_refresh_worker_preserves_custom_mapping_and_publishes_discovery(
    tmp_path: Path,
) -> None:
    import sys

    import yaml

    library = tmp_path / "library"
    (library / "Show").mkdir(parents=True)
    shows = tmp_path / "shows"
    shows.mkdir()
    fragment = shows / "show.yaml"
    fragment.write_text(
        "# show note\nseries:\n  - name: Show\n    path: Show\n"
        "    url: https://watch.dropout.tv/show\n    seasons:\n"
        "      - dropout: 28\n        to_season: 27 # custom destination\n"
        '        title: "Custom season"\n'
        "        url: https://watch.dropout.tv/custom-season\n"
        "        only_episodes: [4]\n        remap:\n"
        "          - dropout_episode: 4\n            to_season: 27\n"
        '            to_episode: 9\n            title: "Custom episode"\n'
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {library}\nold_dir: {tmp_path / 'old'}\nimports: [shows/show.yaml]\n"
    )
    script = (
        "import sys\nfrom yt_dlp_emby.server import services,worker\n"
        "from yt_dlp_emby.extract import DropoutListing\n"
        "services.discover_dropout_source=lambda *a,**k: ["
        "{'dropout':28,'url':'https://watch.dropout.tv/discovered-28','to_season':28,'title':'Remote'},"
        "{'dropout':29,'url':'https://watch.dropout.tv/discovered-29','to_season':29,'title':'New'}]\n"
        "services.extract_dropout_season=lambda *a,**k: [DropoutListing(url='https://watch.dropout.tv/videos/four',title='Remote episode',dropout_episode=4)]\n"
        "sys.exit(worker.main())\n"
    )
    with TestClient(
        create_app(
            data_dir=tmp_path,
            environ={},
            worker_command_factory=lambda _: [sys.executable, "-c", script],
        )
    ) as client:
        client.post("/api/setup", json={"password": "test-password"})
        response = client.post(
            "/api/jobs",
            json={"kind": "refresh", "items": [{"platform": "dropout", "slug": "show"}]},
        )
        assert response.status_code == 202, response.text
        job = _wait(client, response.json()["job_id"])
        assert job["status"] == "succeeded", job
        seasons = yaml.safe_load(fragment.read_text())["series"][0]["seasons"]
        assert seasons[0]["to_season"] == 27
        assert seasons[0]["url"] == "https://watch.dropout.tv/custom-season"
        assert seasons[0]["title"] == "Custom season"
        assert seasons[0]["only_episodes"] == [4]
        assert seasons[1]["enabled"] is False
        assert "# show note" in fragment.read_text()
        assert "# custom destination" in fragment.read_text()
        assert '"Custom season"' in fragment.read_text()
        plan = client.get("/api/plans/latest").json()
        row = plan["sources"]["dropout"]["items"][0]
        assert row["action"] == "download", plan
        assert row["code"] == "S27E09"
        assert row["title"] == "Custom episode"
        detail = client.get("/api/series/dropout/show").json()
        assert detail["missing_count"] == 1, detail
        assert not (library / "Show" / "Season 27").exists()
        assert not (tmp_path / "old").exists()
