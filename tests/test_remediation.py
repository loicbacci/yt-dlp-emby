"""Coverage for phases 1–3 of the backend remediation plan."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from yt_dlp_emby.config import ConfigError, resolve_settings, write_config
from yt_dlp_emby.events import merge_plan_source, parse_events_file
from yt_dlp_emby.library import episode_stem, season_folder_name
from yt_dlp_emby.server.series_discover import assert_public_catalog_url
from yt_dlp_emby.youtube_manifest import load_youtube_manifest

COOKIE = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tNAME\tvalue\n"


def test_season_folder_name_specials() -> None:
    assert season_folder_name(0) == "Specials"
    assert season_folder_name(1) == "Season 1"


def test_episode_stem_truncates_to_200_bytes(tmp_path: Path) -> None:
    dest = tmp_path / "Season 1"
    dest.mkdir()
    stem = episode_stem("Channel", 1, 1, "é" * 400, dest=dest)
    assert len(f"{stem}.mkv".encode("utf-8")) <= 200


def test_episode_stem_disambiguates_collision(tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "Season 1"
    dest.mkdir()
    stem = episode_stem("Channel", 1, 1, "Same")
    (dest / f"{stem}.mkv").write_bytes(b"x")
    monkeypatch.setattr(
        "yt_dlp_emby.library.find_episode_mkv",
        lambda *_args, **_kwargs: dest / "other.mkv",
    )
    second = episode_stem("Channel", 1, 1, "Same", dest=dest)
    assert second.endswith("-2")


def test_cookie_precedence_cli_over_env_manifest_file(tmp_path: Path) -> None:
    file_jar = tmp_path / "file.txt"
    env_jar = tmp_path / "env.txt"
    manifest_jar = tmp_path / "manifest.txt"
    cli_jar = tmp_path / "cli.txt"
    for path in (file_jar, env_jar, manifest_jar, cli_jar):
        path.write_text(COOKIE, encoding="utf-8")
    (tmp_path / "config.toml").write_text(
        f'cookies = "{file_jar}"\n[fallback]\nlibrary = "/lib"\nold_dir = "/old"\n',
        encoding="utf-8",
    )
    common = dict(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        cwd=tmp_path,
        auto_cookies=False,
    )
    from_file = resolve_settings(
        **common,
        environ={"YT_DLP_EMBY_CONFIG": str(tmp_path / "config.toml")},
        use_file_cookies=True,
    )
    assert from_file.cookiefile == file_jar
    from_manifest = resolve_settings(
        **common,
        environ={"YT_DLP_EMBY_CONFIG": str(tmp_path / "config.toml")},
        manifest_cookies=str(manifest_jar),
        use_file_cookies=True,
    )
    assert from_manifest.cookiefile == manifest_jar
    from_env = resolve_settings(
        **common,
        environ={
            "YT_DLP_EMBY_CONFIG": str(tmp_path / "config.toml"),
            "YT_DLP_EMBY_COOKIES": str(env_jar),
        },
        manifest_cookies=str(manifest_jar),
        use_file_cookies=True,
    )
    assert from_env.cookiefile == env_jar
    from_cli = resolve_settings(
        **common,
        cookiefile=str(cli_jar),
        environ={
            "YT_DLP_EMBY_CONFIG": str(tmp_path / "config.toml"),
            "YT_DLP_EMBY_COOKIES": str(env_jar),
        },
        manifest_cookies=str(manifest_jar),
        use_file_cookies=True,
    )
    assert from_cli.cookiefile == cli_jar


def test_write_config_mode_0640(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    write_config(path, {"library": "/lib", "old_dir": "/old"})
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_atomic_write_private_mode_600(tmp_path: Path) -> None:
    from yt_dlp_emby.cache import atomic_write_private

    path = tmp_path / "secret.json"
    atomic_write_private(path, '{"ok": true}\n', mode=0o600)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_series_name_rejects_traversal(tmp_path: Path) -> None:
    path = tmp_path / "youtube.yaml"
    path.write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: ../escape\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLx\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match=r"/|\\\\|\\.\\."):
        load_youtube_manifest(path)


def test_series_name_rejects_slash(tmp_path: Path) -> None:
    path = tmp_path / "youtube.yaml"
    path.write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: foo/bar\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLx\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="name"):
        load_youtube_manifest(path)


def test_skip_remap_does_not_require_to_fields(tmp_path: Path) -> None:
    from yt_dlp_emby.dropout_manifest import load_dropout_manifest

    path = tmp_path / "dropout.yaml"
    path.write_text(
        f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Show
    path: Show
    url: https://watch.dropout.tv/show
    seasons:
      - dropout: 1
        remap:
          - dropout_episode: 1
            skip: true
""",
        encoding="utf-8",
    )
    manifest = load_dropout_manifest(path)
    assert manifest.series[0].sources[0].seasons[0].remap[0].skip is True


def test_schema_requires_to_fields_without_skip(tmp_path: Path) -> None:
    from yt_dlp_emby.dropout_manifest import load_dropout_manifest

    path = tmp_path / "dropout.yaml"
    path.write_text(
        f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Show
    path: Show
    url: https://watch.dropout.tv/show
    seasons:
      - dropout: 1
        remap:
          - dropout_episode: 1
""",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="to_season"):
        load_dropout_manifest(path)


def test_torn_plan_recovers_on_merge(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{not json", encoding="utf-8")
    merge_plan_source(
        plan,
        "youtube",
        {"ok": True, "error": None, "seasons": [], "items": []},
        force=False,
    )
    data = json.loads(plan.read_text(encoding="utf-8"))
    assert data["sources"]["youtube"]["ok"] is True


def test_parse_events_skips_bad_lines(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"event":"ok"}\nnot-json\n{"event":"also"}\n',
        encoding="utf-8",
    )
    events = parse_events_file(path)
    assert [item["event"] for item in events] == ["ok", "also"]


def test_assert_public_catalog_url_ssrf() -> None:
    with pytest.raises(ConfigError):
        assert_public_catalog_url("http://127.0.0.1/x")
    with pytest.raises(ConfigError):
        assert_public_catalog_url("http://169.254.169.254/latest")
    with pytest.raises(ConfigError):
        assert_public_catalog_url("file:///etc/passwd")


def test_runner_events_bounded(tmp_path: Path) -> None:
    from yt_dlp_emby.server.runner import MAX_EVENTS, RunManager

    runner = RunManager(tmp_path)
    for index in range(20_000):
        runner._append_event({"event": "progress", "n": index})
    assert len(runner._events) <= MAX_EVENTS
    assert len(runner._events) <= 5000


def test_jpeg_rejects_svg() -> None:
    from yt_dlp_emby.images import jpeg_bytes_from_image

    with pytest.raises(ValueError, match="svg"):
        jpeg_bytes_from_image(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>")
