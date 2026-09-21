import json
from pathlib import Path

from yt_dlp_emby.events import emit
from yt_dlp_emby.server.plan_series import patch_series_plan, plan_path
from yt_dlp_emby.server.refresh_stamp import series_refresh_payload

TWO_SHOW_PLAN = {
    "generated_at": "2026-01-01T00:00:00",
    "force": False,
    "sources": {
        "dropout": {
            "ok": True,
            "error": None,
            "seasons": [
                {"slug": "game-changer", "dest_season": 1, "download": 2},
                {"slug": "dimension-20", "dest_season": 21, "download": 3},
            ],
            "items": [
                {
                    "slug": "game-changer",
                    "id": "dropout|game-changer|S01E01",
                    "action": "download",
                },
                {
                    "slug": "dimension-20",
                    "id": "dropout|dimension-20|S21E01",
                    "action": "download",
                },
            ],
        }
    },
}


def _write_show(tmp_path: Path) -> None:
    (tmp_path / "dropout.yaml").write_text(
        "series:\n"
        "  - name: Game Changer\n"
        "    path: Game Changer\n"
        "    url: https://watch.dropout.tv/gc\n"
        "    seasons:\n"
        "      - dropout: 1\n",
        encoding="utf-8",
    )
    plan_path(tmp_path).write_text(json.dumps(TWO_SHOW_PLAN), encoding="utf-8")


def test_patch_series_plan_replaces_one_slug(tmp_path, monkeypatch) -> None:
    _write_show(tmp_path)
    monkeypatch.setattr(
        "yt_dlp_emby.server.plan_series._web_settings",
        lambda *_args, **_kwargs: object(),
    )

    def fake_run(_manifest, _settings) -> None:
        emit(
            {
                "event": "season",
                "platform": "dropout",
                "slug": "game-changer",
                "dest_season": 1,
                "download": 0,
            }
        )
        emit(
            {
                "event": "item",
                "platform": "dropout",
                "slug": "game-changer",
                "id": "dropout|game-changer|S01E09",
                "action": "download",
            }
        )

    monkeypatch.setattr("yt_dlp_emby.dropout.run_dropout", fake_run)
    patch_series_plan(tmp_path, "dropout", "game-changer", environ={})
    data = json.loads(plan_path(tmp_path).read_text(encoding="utf-8"))
    block = data["sources"]["dropout"]
    assert [row["slug"] for row in block["seasons"]] == [
        "dimension-20",
        "game-changer",
    ]
    assert [row["id"] for row in block["items"]] == [
        "dropout|dimension-20|S21E01",
        "dropout|game-changer|S01E09",
    ]
    stamps = series_refresh_payload(tmp_path, "dropout", "game-changer")
    assert stamps["disk"]
    other = series_refresh_payload(tmp_path, "dropout", "dimension-20")
    assert other["disk"] is None


def _clip_library(tmp_path: Path) -> None:
    lib = tmp_path / "lib"
    dest = lib / "Clip" / "Season 1"
    dest.mkdir(parents=True)
    (dest / "Clip - S01E01 - Pilot.mkv").write_bytes(b"x")
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "clip.yaml").write_text(
        "series:\n  - name: Clip\n    path: Clip\n    url: https://watch.dropout.tv/c\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nimports:\n  - shows/clip.yaml\nseries: []\n",
        encoding="utf-8",
    )


def _clip_plan(*, force: bool = False, slug: str = "clip") -> dict:
    return {
        "generated_at": "2026-01-01T00:00:00",
        "force": force,
        "sources": {
            "dropout": {
                "ok": True,
                "error": None,
                "seasons": [
                    {
                        "slug": slug,
                        "dest_season": 1,
                        "download": 2,
                        "skip": 0,
                        "replace": 0,
                        "unmapped": 0,
                    }
                ],
                "items": [
                    {
                        "slug": slug,
                        "id": f"dropout|{slug}|S01E01",
                        "action": "download",
                        "code": "S01E01",
                        "dest_season": 1,
                    },
                    {
                        "slug": slug,
                        "id": f"dropout|{slug}|S01E02",
                        "action": "download",
                        "code": "S01E02",
                        "dest_season": 1,
                    },
                ],
            }
        },
    }


def test_reconcile_drops_downloads_already_on_disk(tmp_path: Path) -> None:
    from yt_dlp_emby.server.plan_series import reconcile_plan_with_library

    _clip_library(tmp_path)
    live = reconcile_plan_with_library(tmp_path, _clip_plan(), {})
    items = live["sources"]["dropout"]["items"]
    assert [row["id"] for row in items] == ["dropout|clip|S01E02"]
    assert live["sources"]["dropout"]["seasons"][0]["download"] == 1


def test_reconcile_keeps_on_disk_when_force(tmp_path: Path) -> None:
    from yt_dlp_emby.server.plan_series import reconcile_plan_with_library

    _clip_library(tmp_path)
    live = reconcile_plan_with_library(tmp_path, _clip_plan(force=True), {})
    assert len(live["sources"]["dropout"]["items"]) == 2


def test_reconcile_joins_plan_slug_to_file_stem(tmp_path: Path) -> None:
    from yt_dlp_emby.server.plan_series import reconcile_plan_with_library

    lib = tmp_path / "lib"
    dest = lib / "Adventuring Party" / "Specials"
    dest.mkdir(parents=True)
    (dest / "Adventuring Party - S00E12 - Cut.mkv").write_bytes(b"x")
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "dimension-20-adventuring-party.yaml").write_text(
        "series:\n"
        "  - name: Dimension 20's Adventuring Party\n"
        "    path: Adventuring Party\n"
        "    url: https://watch.dropout.tv/ap\n"
        "    seasons:\n      - dropout: 1\n        to_season: 0\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nimports:\n  - shows/dimension-20-adventuring-party.yaml\nseries: []\n",
        encoding="utf-8",
    )
    plan = {
        "generated_at": "2026-01-01T00:00:00",
        "force": False,
        "sources": {
            "dropout": {
                "ok": True,
                "error": None,
                "seasons": [
                    {
                        "slug": "dimension-20-s-adventuring-party",
                        "dest_season": 0,
                        "download": 1,
                        "skip": 0,
                        "replace": 0,
                        "unmapped": 0,
                    }
                ],
                "items": [
                    {
                        "slug": "dimension-20-s-adventuring-party",
                        "id": "dropout|dimension-20-s-adventuring-party|S00E12",
                        "action": "download",
                        "code": "S00E12",
                        "dest_season": 0,
                    }
                ],
            }
        },
    }
    live = reconcile_plan_with_library(tmp_path, plan, {})
    assert live["sources"]["dropout"]["items"] == []
    assert live["sources"]["dropout"]["seasons"][0]["download"] == 0
