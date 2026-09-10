from pathlib import Path

from yt_dlp_emby.doctor import run_doctor
from yt_dlp_emby.style import strip_ansi


def test_doctor_ok_with_ffmpeg_and_cookies(tmp_path: Path, capsys) -> None:
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tNAME\tvalue\n")
    staging = tmp_path / "staging"
    library = tmp_path / "lib"
    library.mkdir()
    code = run_doctor(
        ffmpeg_location=str(ffmpeg),
        cookies=str(cookies),
        staging=str(staging),
        library=str(library),
        environ={},
        cwd=tmp_path,
    )
    out = strip_ansi(capsys.readouterr().out)
    assert code == 0
    assert "ok      ffmpeg" in out
    assert "ok      cookies" in out
    assert "ok      staging" in out
    assert "ok      library" in out
    assert "doctor: all required checks passed" in out


def test_doctor_fails_on_empty_cookies(tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    code = run_doctor(
        ffmpeg_location=str(ffmpeg),
        cookies=str(cookies),
        environ={},
        cwd=tmp_path,
    )
    assert code == 1
