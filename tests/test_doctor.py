from collections import namedtuple
from pathlib import Path

from yt_dlp_emby.doctor import FAIL_FREE_BYTES, run_doctor
from yt_dlp_emby.style import strip_ansi

_Disk = namedtuple("_Disk", "total used free")


def _ffmpeg(tmp_path: Path) -> Path:
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    return ffmpeg


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
    ffmpeg = _ffmpeg(tmp_path)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    code = run_doctor(
        ffmpeg_location=str(ffmpeg),
        cookies=str(cookies),
        environ={},
        cwd=tmp_path,
    )
    assert code == 1


def test_doctor_warns_when_node_missing(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("yt_dlp_emby.doctor.find_node", lambda: None)
    library = tmp_path / "lib"
    library.mkdir()
    code = run_doctor(
        ffmpeg_location=str(_ffmpeg(tmp_path)),
        library=str(library),
        environ={},
        cwd=tmp_path,
    )
    captured = capsys.readouterr()
    combined = strip_ansi(captured.out + captured.err)
    assert code == 0
    assert "node not found" in combined


def test_doctor_fails_when_staging_unwritable(tmp_path: Path, monkeypatch, capsys) -> None:
    def boom(*_args: object, **_kwargs: object) -> str:
        raise OSError("read-only filesystem")

    monkeypatch.setattr("yt_dlp_emby.doctor.tempfile.mkstemp", boom)
    staging = tmp_path / "staging"
    staging.mkdir()
    code = run_doctor(
        ffmpeg_location=str(_ffmpeg(tmp_path)),
        staging=str(staging),
        environ={},
        cwd=tmp_path,
    )
    err = strip_ansi(capsys.readouterr().err)
    assert code == 1
    assert "staging is not writable" in err


def test_doctor_fails_when_disk_full(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "yt_dlp_emby.doctor.shutil.disk_usage",
        lambda _path: _Disk(total=10**12, used=10**12, free=FAIL_FREE_BYTES - 1),
    )
    staging = tmp_path / "staging"
    library = tmp_path / "lib"
    staging.mkdir()
    library.mkdir()
    code = run_doctor(
        ffmpeg_location=str(_ffmpeg(tmp_path)),
        staging=str(staging),
        library=str(library),
        environ={},
        cwd=tmp_path,
    )
    err = strip_ansi(capsys.readouterr().err)
    assert code == 1
    assert "has only" in err
    assert "free" in err


def test_doctor_fails_when_library_missing(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "no-such-library"
    code = run_doctor(
        ffmpeg_location=str(_ffmpeg(tmp_path)),
        library=str(missing),
        environ={},
        cwd=tmp_path,
    )
    err = strip_ansi(capsys.readouterr().err)
    assert code == 1
    assert "library does not exist" in err
