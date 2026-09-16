from pathlib import Path

import pytest

from yt_dlp_emby.cookies import (
    cookies_file_usable,
    inspect_cookie_jars,
    sandbox_cookiefile,
    write_cookie_jar,
)


def _netscape(body: str = ".watch.dropout.tv\tTRUE\t/\tTRUE\t0\t_session\tabc\n") -> str:
    return "# Netscape HTTP Cookie File\n" + body


def test_cookies_file_usable(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text("# Netscape HTTP Cookie File\n")
    assert cookies_file_usable(path) is False
    path.write_text(_netscape())
    assert cookies_file_usable(path) is True


def test_sandbox_cookiefile_keeps_original_if_ydl_wipes(tmp_path: Path) -> None:
    source = tmp_path / "dropout-cookies.txt"
    source.write_text(_netscape())
    with sandbox_cookiefile(source) as cookiefile:
        assert cookiefile != str(source)
        Path(cookiefile).write_text("")
    assert source.read_text() == _netscape()


def test_sandbox_cookiefile_never_copies_ydl_jar_back(tmp_path: Path) -> None:
    source = tmp_path / "dropout-cookies.txt"
    source.write_text(_netscape())
    refreshed = _netscape(".watch.dropout.tv\tTRUE\t/\tTRUE\t0\t_session\tnew\n")
    with sandbox_cookiefile(source) as cookiefile:
        Path(cookiefile).write_text(refreshed)
    assert source.read_text() == _netscape()


def test_sandbox_cookiefile_none() -> None:
    with sandbox_cookiefile(None) as cookiefile:
        assert cookiefile is None


def test_inspect_cookie_jars_omits_file_text(tmp_path: Path) -> None:
    secret = "super-secret-cookie-value"
    (tmp_path / "cookies.txt").write_text(
        _netscape(f".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t{secret}\n")
    )
    payload = inspect_cookie_jars(tmp_path, {})
    assert secret not in str(payload)
    youtube = payload["jars"]["youtube"]
    assert youtube["exists"] is True
    assert youtube["usable"] is True
    assert youtube["filename"] == "cookies.txt"
    dropout = payload["jars"]["dropout"]
    assert dropout["exists"] is False
    assert dropout["usable"] is False
    assert payload["env_set"] is False


def test_inspect_cookie_jars_env_flag_without_contents(tmp_path: Path) -> None:
    payload = inspect_cookie_jars(
        tmp_path, {"YT_DLP_EMBY_COOKIES": "/secret/cookies.txt"}
    )
    assert payload["env_set"] is True
    assert payload["env_name"] == "YT_DLP_EMBY_COOKIES"
    assert payload["env_path"] == "/secret/cookies.txt"


def test_write_cookie_jar_youtube_and_dropout(tmp_path: Path) -> None:
    youtube = write_cookie_jar(tmp_path, "youtube", _netscape(".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t1\n"))
    dropout = write_cookie_jar(tmp_path, "dropout", _netscape())
    assert youtube == tmp_path / "cookies.txt"
    assert dropout == tmp_path / "dropout-cookies.txt"
    assert cookies_file_usable(youtube)
    assert cookies_file_usable(dropout)


def test_write_cookie_jar_rejects_empty_and_unknown(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty"):
        write_cookie_jar(tmp_path, "youtube", "# Netscape HTTP Cookie File\n")
    with pytest.raises(ValueError, match="unknown"):
        write_cookie_jar(tmp_path, "other", _netscape())


def test_write_cookie_jar_confined_filename(tmp_path: Path) -> None:
    path = write_cookie_jar(
        tmp_path, "dropout", _netscape(), filename="custom-drop.txt"
    )
    assert path == tmp_path / "custom-drop.txt"
    assert cookies_file_usable(path)
