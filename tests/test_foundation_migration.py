from pathlib import Path

from yt_dlp_emby.server.migration import archive_legacy_state


def test_migration_archives_only_derived_state_once(tmp_path: Path) -> None:
    canonical = {
        "dropout.yaml": "series: []\n",
        "config.toml": "# settings\n",
        "cookies.txt": "private fixture",
    }
    for name, content in canonical.items():
        (tmp_path / name).write_text(content)
    (tmp_path / "cache").mkdir()
    (tmp_path / "plan.json").write_text('{"old":true}')
    (tmp_path / "events.jsonl").write_text("old event\n")
    (tmp_path / "download-only.json").write_text('{"ids":["old"]}')
    (tmp_path / "cache" / "refresh.json").write_text("{}")
    media = tmp_path / "media"
    media.mkdir()
    (media / "episode.mkv").write_bytes(b"media")
    archive_legacy_state(tmp_path)
    archive = tmp_path / "legacy-state"
    assert (archive / "plan.json").read_text() == '{"old":true}'
    assert (archive / "cache-refresh.json").exists()
    assert not (tmp_path / "download-only.json").exists()
    assert all((tmp_path / name).read_text() == content for name, content in canonical.items())
    assert (media / "episode.mkv").read_bytes() == b"media"
    assert (archive / "plan.json").stat().st_mode & 0o777 == 0o600
    marker = (archive / "migration.json").read_bytes()
    (tmp_path / "plan.json").write_text("later state")
    archive_legacy_state(tmp_path)
    assert (archive / "migration.json").read_bytes() == marker
    assert (tmp_path / "plan.json").read_text() == "later state"


def test_migration_does_not_follow_legacy_file_or_cache_symlinks(tmp_path: Path) -> None:
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    source = outside / "refresh.json"
    source.write_text("external")
    (tmp_path / "cache").symlink_to(outside, target_is_directory=True)
    (tmp_path / "plan.json").symlink_to(source)
    archive_legacy_state(tmp_path)
    assert source.read_text() == "external"
    assert (tmp_path / "plan.json").is_symlink()
    assert not (tmp_path / "legacy-state" / "plan.json").exists()
