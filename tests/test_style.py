from yt_emby.log import fit_line, format_dry_run_row, format_run_summary, warn
from yt_emby.style import (
    GREEN,
    RED,
    YELLOW,
    color_enabled,
    green,
    paint,
    strip_ansi,
    visible_len,
)


def test_color_enabled_respects_no_color(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    assert color_enabled()
    monkeypatch.setenv("NO_COLOR", "1")
    assert not color_enabled()


def test_paint_force_color(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    styled = green("ok")
    assert styled.startswith(GREEN)
    assert styled.endswith("\033[0m")
    assert strip_ansi(styled) == "ok"
    monkeypatch.setenv("NO_COLOR", "1")
    assert green("ok") == "ok"


def test_visible_len_ignores_ansi() -> None:
    styled = paint("hello", GREEN, enabled=True)
    assert visible_len(styled) == 5
    assert strip_ansi(styled) == "hello"


def test_fit_line_truncates_visible_width(monkeypatch) -> None:
    class Tty:
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr(
        "yt_emby.log.shutil.get_terminal_size",
        lambda *a, **k: type("Size", (), {"columns": 10})(),
    )
    styled = paint("abcdefghijklmnop", GREEN, enabled=True)
    fitted = fit_line(styled, Tty())
    assert visible_len(fitted) == 10
    assert fitted.endswith("…") or fitted.endswith("…\033[0m")
    assert GREEN in fitted


def test_dry_run_row_and_summary_color(monkeypatch) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    row = format_dry_run_row("download", "S27E01", "Welcome", "Season 27/")
    assert strip_ansi(row).startswith("download")
    assert GREEN in row
    summary = format_run_summary(downloaded=1, skipped=2, failed=3)
    assert strip_ansi(summary) == "Done  downloaded=1  skipped=2  failed=3"
    assert RED in summary
    interrupted = format_run_summary(interrupted=True, remaining=4)
    assert "interrupted" in strip_ansi(interrupted)
    assert YELLOW in interrupted


def test_warn_prefix_color(monkeypatch, capsys) -> None:
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    warn("hello")
    err = capsys.readouterr().err
    assert "warning: hello" in strip_ansi(err)
    assert YELLOW in err
