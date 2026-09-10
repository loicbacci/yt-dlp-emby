from pathlib import Path

import pytest

from yt_emby.bench import parse_size, run_bench
from yt_emby.config import resolve_settings


def test_parse_size() -> None:
    assert parse_size("256") == 256
    assert parse_size("256B") == 256
    assert parse_size("64M") == 64 * 1024 * 1024
    assert parse_size("1.5G") == int(1.5 * 1024 * 1024 * 1024)
    with pytest.raises(ValueError):
        parse_size("nope")


def test_run_bench_copies_and_cleans(tmp_path: Path) -> None:
    dest = tmp_path / "share"
    dest.mkdir()
    source = tmp_path / "staging"
    source.mkdir()
    assert run_bench(dest, size=64 * 1024, source_dir=source, show_progress=False) == 0
    assert list(dest.iterdir()) == []
    assert list(source.iterdir()) == []


def test_bench_dest_from_config(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'library = "/from/file/lib"\nold_dir = "/from/file/old"\nbench_dest = "/from/file/bench"\n'
    )
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    settings = resolve_settings(
        config_path=str(config),
        ffmpeg_location=str(ffmpeg),
        environ={},
        cwd=tmp_path,
    )
    assert settings.bench_dest == Path("/from/file/bench")


def test_cli_dest_overrides_bench_dest(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'library = "/from/file/lib"\nold_dir = "/from/file/old"\nbench_dest = "/from/file/bench"\n'
    )
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    settings = resolve_settings(
        config_path=str(config),
        ffmpeg_location=str(ffmpeg),
        bench_dest="/from/cli/bench",
        environ={},
        cwd=tmp_path,
    )
    assert settings.bench_dest == Path("/from/cli/bench")
