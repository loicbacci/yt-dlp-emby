from pathlib import Path

from yt_dlp_emby.cookies import cookies_file_usable, sandbox_cookiefile


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
