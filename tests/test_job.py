"""TTY-vs-piped snapshots for job work rows and log line fitting."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from yt_dlp_emby.config import Settings
from yt_dlp_emby.job import WorkRow, print_work_rows
from yt_dlp_emby.log import fit_line


class _FakeStream(io.StringIO):
    def __init__(self, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:  # noqa: D102
        return self._tty


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        **overrides,
    )


def _rows() -> list[WorkRow]:
    return [
        WorkRow(action="download", code="S01E01", title="Pilot", folder="Season 1"),
        WorkRow(action="skip", code="S01E02", title="Second", folder="Season 1"),
        WorkRow(action="rename", code="S01E03", title="Third", folder="Season 1"),
    ]


def _render(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tty: bool, **overrides) -> str:
    # Wide terminal so fit_line never truncates these short rows.
    monkeypatch.setattr("yt_dlp_emby.log._terminal_columns", lambda: 200)
    fake = _FakeStream(tty)
    monkeypatch.setattr(sys, "stdout", fake)
    print_work_rows(_settings(tmp_path, **overrides), _rows())
    return fake.getvalue()


def test_tty_hides_download_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _render(monkeypatch, tmp_path, tty=True)
    assert "S01E01" not in out  # download: progress bars cover it on a TTY
    assert "S01E02" not in out  # skip: verbose-only
    assert "S01E03" in out  # rename: always shown


def test_piped_shows_download_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _render(monkeypatch, tmp_path, tty=False)
    assert "S01E01" in out  # piped: no bars, so rows are the only signal
    assert "S01E02" not in out  # skip stays verbose-only even when piped
    assert "S01E03" in out


def test_verbose_tty_shows_all(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _render(monkeypatch, tmp_path, tty=True, verbose=True)
    assert "S01E01" in out
    assert "S01E02" in out
    assert "S01E03" in out


def test_dry_run_tty_shows_download_rows(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    out = _render(monkeypatch, tmp_path, tty=True, dry_run=True)
    assert "S01E01" in out  # dry-run: rows are the plan, no bars to cover them
    assert "S01E03" in out


def test_fit_line_truncates_only_on_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("yt_dlp_emby.log._terminal_columns", lambda: 20)
    long_text = "S01E01  " + "x" * 60
    tty_out = fit_line(long_text, _FakeStream(True))
    assert tty_out.endswith("…")
    assert len(tty_out) < len(long_text)
    assert fit_line(long_text, _FakeStream(False)) == long_text
    assert fit_line(long_text, object()) == long_text
