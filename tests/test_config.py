import os
from pathlib import Path

import pytest

from yt_dlp_emby.config import ConfigError, FFmpegNotFoundError, MissingPathError, resolve_settings
from yt_dlp_emby.ffmpeg import FFMPEG_INSTALL_HELP, find_ffmpeg


def test_cli_flags_override_env_and_config(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('library = "/from/file/lib"\nold_dir = "/from/file/old"\n')
    env = {
        "YT_DLP_EMBY_LIBRARY": "/from/env/lib",
        "YT_DLP_EMBY_OLD_DIR": "/from/env/old",
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
        "YT_DLP_EMBY_LIBRARY": "/from/env/lib",
        "YT_DLP_EMBY_OLD_DIR": "/from/env/old",
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


def test_yt_dlp_emby_config_env_selects_file(tmp_path: Path) -> None:
    config = tmp_path / "alt.toml"
    config.write_text('library = "/from/alt/lib"\nold_dir = "/from/alt/old"\n')
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={"YT_DLP_EMBY_CONFIG": str(config)},
        cwd=tmp_path,
    )
    assert settings.library == Path("/from/alt/lib")


def test_missing_library_and_old_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(MissingPathError) as exc:
        resolve_settings(ffmpeg_location="/usr/bin/ffmpeg", environ={}, cwd=tmp_path)
    message = str(exc.value)
    assert "library" in message
    assert "old_dir" in message
    assert "--library" in message or "YT_DLP_EMBY_LIBRARY" in message


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
    assert find_ffmpeg(None, environ={"YT_DLP_EMBY_FFMPEG": str(binary)}) == binary.resolve()


def test_find_ffmpeg_raises_with_install_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp_emby.ffmpeg.shutil.which", lambda _name: None)
    with pytest.raises(FFmpegNotFoundError) as exc:
        find_ffmpeg(None, environ={})
    assert "apt install ffmpeg" in str(exc.value)
    assert "brew install ffmpeg" in FFMPEG_INSTALL_HELP


def test_verbose_from_env(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={"YT_DLP_EMBY_VERBOSE": "1"},
        cwd=tmp_path,
    )
    assert settings.verbose is True


def test_quiet_overrides_env_verbose(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        quiet=True,
        environ={"YT_DLP_EMBY_VERBOSE": "1"},
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
        environ={"YT_DLP_EMBY_VERBOSE": "1"},
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
        environ={"YT_DLP_EMBY_STAGING": "/local/tmp"},
        cwd=tmp_path,
    )
    assert settings.staging == Path("/local/tmp")


def test_force_refetch_from_env(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={"YT_DLP_EMBY_FORCE_REFETCH": "1"},
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


def test_debug_does_not_hide_progress(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        debug=True,
        environ={},
        cwd=tmp_path,
    )
    assert settings.debug is True
    assert settings.verbose is False
    assert settings.show_progress is True


def test_debug_from_env(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={"YT_DLP_EMBY_DEBUG": "1"},
        cwd=tmp_path,
    )
    assert settings.debug is True
    assert settings.show_progress is True


def test_verbose_still_hides_progress_with_debug(tmp_path: Path) -> None:
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        verbose=True,
        debug=True,
        environ={},
        cwd=tmp_path,
    )
    assert settings.debug is True
    assert settings.verbose is True
    assert settings.show_progress is False


def test_no_default_library_path() -> None:
    source = Path("src/yt_dlp_emby/config.py").read_text()
    assert "/mnt/nas" not in source
    assert "/path/to/library" not in source


def test_legacy_yt_emby_env_still_works(tmp_path: Path) -> None:
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={
            "YT_EMBY_LIBRARY": "/from/legacy/lib",
            "YT_EMBY_OLD_DIR": "/from/legacy/old",
        },
        cwd=tmp_path,
    )
    assert settings.library == Path("/from/legacy/lib")
    assert settings.old_dir == Path("/from/legacy/old")


def test_cookiefile_from_cwd_cookies_txt(tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tNAME\tvalue\n")
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
    )
    assert settings.cookiefile == cookies


def test_cookiefile_from_cwd_auto_cookie_name(tmp_path: Path) -> None:
    youtube = tmp_path / "cookies.txt"
    youtube.write_text(
        "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tNAME\tvalue\n"
    )
    dropout = tmp_path / "dropout-cookies.txt"
    dropout.write_text(
        "# Netscape HTTP Cookie File\n.watch.dropout.tv\tTRUE\t/\tTRUE\t0\t_session\tabc\n"
    )
    settings = resolve_settings(
        library="/lib",
        old_dir="/old",
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
        auto_cookie_name="dropout-cookies.txt",
    )
    assert settings.cookiefile == dropout


def test_empty_cookiefile_raises(tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    with pytest.raises(ConfigError, match="empty"):
        resolve_settings(
            library="/lib",
            old_dir="/old",
            ffmpeg_location="/usr/bin/ffmpeg",
            cookiefile=str(cookies),
            environ={},
            cwd=tmp_path,
            auto_cookies=False,
        )


def test_sonarr_url_from_cli_env_config(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'library = "/from/file/lib"\nold_dir = "/from/file/old"\n'
        'sonarr_url = "http://from-file:8989"\n'
        'sonarr_api_key = "file-key"\n',
        encoding="utf-8",
    )
    from_file = resolve_settings(
        config_path=str(config),
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
        auto_cookies=False,
    )
    assert from_file.sonarr_url == "http://from-file:8989"
    assert from_file.sonarr_api_key == "file-key"
    env = {
        "YT_DLP_EMBY_SONARR_URL": "http://from-env:8989",
        "YT_DLP_EMBY_SONARR_API_KEY": "env-key",
    }
    from_env = resolve_settings(
        config_path=str(config),
        ffmpeg_location="/usr/bin/ffmpeg",
        environ=env,
        cwd=tmp_path,
        auto_cookies=False,
    )
    assert from_env.sonarr_url == "http://from-env:8989"
    assert from_env.sonarr_api_key == "env-key"
    from_cli = resolve_settings(
        config_path=str(config),
        ffmpeg_location="/usr/bin/ffmpeg",
        sonarr_url="http://from-cli:8989",
        sonarr_api_key="cli-key",
        environ=env,
        cwd=tmp_path,
        auto_cookies=False,
    )
    assert from_cli.sonarr_url == "http://from-cli:8989"
    assert from_cli.sonarr_api_key == "cli-key"


def test_fallback_table_used_when_manifest_omits_paths(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[fallback]\nlibrary = "/from/fallback/lib"\nold_dir = "/from/fallback/old"\n'
        'staging = "/from/fallback/staging"\n',
        encoding="utf-8",
    )
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
        auto_cookies=False,
    )
    assert settings.library == Path("/from/fallback/lib")
    assert settings.old_dir == Path("/from/fallback/old")
    assert settings.staging == Path("/from/fallback/staging")


def test_fallback_table_wins_over_legacy_top_level(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'library = "/legacy/lib"\nold_dir = "/legacy/old"\n'
        '[fallback]\nlibrary = "/fallback/lib"\nold_dir = "/fallback/old"\n',
        encoding="utf-8",
    )
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
        auto_cookies=False,
    )
    assert settings.library == Path("/fallback/lib")
    assert settings.old_dir == Path("/fallback/old")


def test_manifest_paths_win_over_fallback_file(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[fallback]\nlibrary = "/from/fallback/lib"\nold_dir = "/from/fallback/old"\n',
        encoding="utf-8",
    )
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        manifest_library="/from/yaml/lib",
        manifest_old_dir="/from/yaml/old",
        environ={},
        cwd=tmp_path,
        auto_cookies=False,
    )
    assert settings.library == Path("/from/yaml/lib")
    assert settings.old_dir == Path("/from/yaml/old")


def test_env_wins_over_manifest_and_fallback(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        '[fallback]\nlibrary = "/from/fallback/lib"\nold_dir = "/from/fallback/old"\n',
        encoding="utf-8",
    )
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        manifest_library="/from/yaml/lib",
        manifest_old_dir="/from/yaml/old",
        environ={
            "YT_DLP_EMBY_LIBRARY": "/from/env/lib",
            "YT_DLP_EMBY_OLD_DIR": "/from/env/old",
        },
        cwd=tmp_path,
        auto_cookies=False,
    )
    assert settings.library == Path("/from/env/lib")
    assert settings.old_dir == Path("/from/env/old")


def test_manifest_does_not_use_config_cookies(tmp_path: Path) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tNAME\tvalue\n")
    config = tmp_path / "config.toml"
    config.write_text(
        '[fallback]\nlibrary = "/lib"\nold_dir = "/old"\n'
        f'cookies = "{cookies}"\n',
        encoding="utf-8",
    )
    settings = resolve_settings(
        ffmpeg_location="/usr/bin/ffmpeg",
        environ={},
        cwd=tmp_path,
        use_file_cookies=False,
        auto_cookies=False,
    )
    assert settings.cookiefile is None


def test_write_config_uses_fallback_table_and_preserves_cookies(tmp_path: Path) -> None:
    from yt_dlp_emby.config import load_config_values, write_config

    path = tmp_path / "config.toml"
    path.write_text('cookies = "keep-me.txt"\nlibrary = "/old"\n', encoding="utf-8")
    write_config(
        path,
        {
            "library": "/new/lib",
            "old_dir": "/new/old",
            "staging": None,
            "bench_dest": None,
            "sonarr_url": "http://sonarr:8989",
            "sonarr_api_key": "secret",
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "[fallback]" in text
    assert "library = " in text
    assert 'sonarr_api_key = "secret"' in text
    assert "keep-me.txt" in text
    assert 'library = "/old"' not in text.split("[fallback]")[0]
    values = load_config_values(path)
    assert values["library"] == "/new/lib"
    assert values["cookies"] == "keep-me.txt"


def test_inspect_config_marks_env_source(tmp_path: Path) -> None:
    from yt_dlp_emby.config import inspect_config

    config = tmp_path / "config.toml"
    config.write_text(
        '[fallback]\nlibrary = "/from/file/lib"\nold_dir = "/from/file/old"\n',
        encoding="utf-8",
    )
    _path, exists, fields = inspect_config(
        environ={"YT_DLP_EMBY_LIBRARY": "/from/env/lib"},
        cwd=tmp_path,
    )
    assert exists is True
    assert fields["library"].source == "env"
    assert fields["library"].env_name == "YT_DLP_EMBY_LIBRARY"
    assert fields["library"].file == "/from/file/lib"
    assert fields["library"].effective == "/from/env/lib"
    assert fields["old_dir"].source == "file"
