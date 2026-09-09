import os
from pathlib import Path

import pytest

from yt_emby.config import ConfigError, FFmpegNotFoundError, MissingPathError, resolve_settings
from yt_emby.ffmpeg import FFMPEG_INSTALL_HELP, find_ffmpeg


def test_cli_flags_override_env_and_config(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('library = "/from/file/lib"\nold_dir = "/from/file/old"\n')
    env = {
        "YT_EMBY_LIBRARY": "/from/env/lib",
        "YT_EMBY_OLD_DIR": "/from/env/old",
    }
    settings = resolve_settings(
        library="/from/cli/lib",
        old_dir="/from/cli/old",
        config_path=str(config),
        ffmpeg_location="/usr/bin/ffmpeg",
        environ=env,
        cwd=tmp_path,
    )
    assert settings.library == Path("/from/cli/lib")
    assert settings.old_dir == Path("/from/cli/old")


def test_env_overrides_config_file(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('library = "/from/file/lib"\nold_dir = "/from/file/old"\n')
    env = {
        "YT_EMBY_LIBRARY": "/from/env/lib",
        "YT_EMBY_OLD_DIR": "/from/env/old",
    }
    settings = resolve_settings(
        config_path=str(config),
        ffmpeg_location="/usr/bin/ffmpeg",
        environ=env,
        cwd=tmp_path,
    )
    assert settings.library == Path("/from/env/lib")
    assert settings.old_dir == Path("/from/env/old")


def test_loads_config_from_explicit_path(tmp_path: Path) -> None:
    config = tmp_path / "custom.toml"
    config.write_text('library = "/from/file/lib"\nold_dir = "/from/file/old"\n')
    settings = resolve_settings(
        config_path=str(config),
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
    )
    assert settings.library == Path("/from/file/lib")
    assert settings.old_dir == Path("/from/file/old")


def test_loads_config_toml_from_cwd_when_present(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text(
        'library = "/from/cwd/lib"\nold_dir = "/from/cwd/old"\n'
    )
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
    )
    assert settings.library == Path("/from/cwd/lib")
    assert settings.old_dir == Path("/from/cwd/old")


def test_yt_emby_config_env_selects_file(tmp_path: Path) -> None:
    config = tmp_path / "alt.toml"
    config.write_text('library = "/from/alt/lib"\nold_dir = "/from/alt/old"\n')
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={"YT_EMBY_CONFIG": str(config)},
        cwd=tmp_path,
    )
    assert settings.library == Path("/from/alt/lib")


def test_missing_library_and_old_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(MissingPathError) as exc:
        resolve_settings(ffmpeg_location="/usr/bin/ffmpeg", environ={}, cwd=tmp_path)
    message = str(exc.value)
    assert "library" in message
    assert "old_dir" in message
    assert "--library" in message or "YT_EMBY_LIBRARY" in message


def test_missing_only_old_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(MissingPathError, match="old_dir"):
        resolve_settings(
            library="/only/lib",
            ffmpeg_location="/usr/bin/ffmpeg",
            environ={},
            cwd=tmp_path,
        )


def test_find_ffmpeg_uses_explicit_path(tmp_path: Path) -> None:
    binary = tmp_path / "ffmpeg"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    assert find_ffmpeg(str(binary), environ={}) == binary.resolve()


def test_find_ffmpeg_uses_env(tmp_path: Path) -> None:
    binary = tmp_path / "ffmpeg"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    assert find_ffmpeg(None, environ={"YT_EMBY_FFMPEG": str(binary)}) == binary.resolve()


def test_find_ffmpeg_raises_with_install_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_emby.ffmpeg.shutil.which", lambda _name: None)
    with pytest.raises(FFmpegNotFoundError) as exc:
        find_ffmpeg(None, environ={})
    assert "apt install ffmpeg" in str(exc.value)
    assert "brew install ffmpeg" in FFMPEG_INSTALL_HELP


def test_verbose_from_env(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={"YT_EMBY_VERBOSE": "1"},
        cwd=tmp_path,
    )
    assert settings.verbose is True


def test_quiet_overrides_env_verbose(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        quiet=True,
        environ={"YT_EMBY_VERBOSE": "1"},
        cwd=tmp_path,
    )
    assert settings.quiet is True
    assert settings.verbose is False
    assert settings.show_progress is False
    assert settings.show_summary is True


def test_silent_disables_verbose(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        silent=True,
        environ={"YT_EMBY_VERBOSE": "1"},
        cwd=tmp_path,
    )
    assert settings.silent is True
    assert settings.verbose is False
    assert settings.show_progress is False
    assert settings.show_summary is False


def test_staging_from_env(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={"YT_EMBY_STAGING": "/local/tmp"},
        cwd=tmp_path,
    )
    assert settings.staging == Path("/local/tmp")


def test_force_refetch_from_env(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={"YT_EMBY_FORCE_REFETCH": "1"},
        cwd=tmp_path,
    )
    assert settings.force_refetch is True


def test_force_refetch_cli_flag(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        force_refetch=True,
        environ={},
        cwd=tmp_path,
    )
    assert settings.force_refetch is True


def test_no_default_library_path() -> None:
    source = Path("src/yt_emby/config.py").read_text()
    assert "/mnt/nas" not in source
    assert "/path/to/library" not in source


def test_cookiefile_from_cwd_cookies_txt(tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
    )
    assert settings.cookiefile == cookies
