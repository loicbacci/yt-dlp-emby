import asyncio
import os
import sys
import textwrap

import pytest

pytest.importorskip("fastapi")

from yt_dlp_emby.server.runner import RunManager, default_command

pytestmark = pytest.mark.web


def _write_youtube_manifest(tmp_path) -> None:
    text = textwrap.dedent(
        f"""
        library: {tmp_path / "lib"}
        old_dir: {tmp_path / "old"}
        series:
          - name: Example Channel
            playlists:
              - url: https://www.youtube.com/playlist?list=PLaaaa
        """
    ).strip()
    (tmp_path / "youtube.yaml").write_text(text, encoding="utf-8")


def _factory(script: str):
    return lambda *a, **k: [sys.executable, "-c", script]


async def _wait_exited(runner: RunManager, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if runner.snapshot()["status"] == "exited":
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"still {runner.snapshot()['status']}")


def test_default_command_argv() -> None:
    argv = default_command(
        "youtube",
        __import__("pathlib").Path("/data/youtube.yaml"),
        dry_run=True,
        verbose=True,
        force=False,
        library="/lib",
        old_dir="/old",
        staging="/staging",
    )
    assert argv[:4] == [sys.executable, "-m", "yt_dlp_emby", "youtube"]
    assert "--manifest" in argv
    assert "--dry-run" in argv
    assert "--verbose" in argv
    assert "--library" in argv and "/lib" in argv
    assert "--force" not in argv


def test_dropout_command_includes_force() -> None:
    argv = default_command(
        "dropout",
        __import__("pathlib").Path("/data/dropout.yaml"),
        dry_run=False,
        verbose=False,
        force=True,
        action="download",
        library=None,
        old_dir=None,
        staging=None,
    )
    assert argv[3] == "dropout"
    assert argv[4] == "download"
    assert "--force" in argv


def test_dropout_layout_verb_argv() -> None:
    argv = default_command(
        "dropout",
        __import__("pathlib").Path("/data/dropout.yaml"),
        dry_run=True,
        verbose=False,
        force=False,
        action="layout",
        library=None,
        old_dir=None,
        staging=None,
    )
    assert argv[3:5] == ["dropout", "layout"]
    assert "--layout" not in argv
    assert "--dry-run" not in argv


def test_dropout_check_verb_argv() -> None:
    argv = default_command(
        "dropout",
        __import__("pathlib").Path("/data/dropout.yaml"),
        dry_run=False,
        verbose=False,
        force=False,
        action="check",
        library=None,
        old_dir=None,
        staging=None,
    )
    assert argv[3:5] == ["dropout", "check"]
    assert "--layout" not in argv
    assert "--dry-run" not in argv
    assert "--force" not in argv


def test_youtube_layout_is_ignored() -> None:
    argv = default_command(
        "youtube",
        __import__("pathlib").Path("/data/youtube.yaml"),
        dry_run=False,
        verbose=False,
        force=False,
        action="layout",
        library=None,
        old_dir=None,
        staging=None,
    )
    assert "layout" not in argv
    assert "--dry-run" not in argv
    assert argv[3] == "youtube"


def test_youtube_force_rejected() -> None:
    runner = RunManager(__import__("pathlib").Path("/tmp"))
    with pytest.raises(ValueError, match="force"):
        asyncio.run(runner.start("youtube", force=True))


def test_dropout_rejects_force_on_layout_start(tmp_path) -> None:
    (tmp_path / "dropout.yaml").write_text(
        "library: /lib\nold_dir: /old\nseries:\n"
        "  - name: X\n    path: X\n    url: https://watch.dropout.tv/x\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    runner = RunManager(tmp_path)
    with pytest.raises(ValueError, match="force"):
        asyncio.run(runner.start("dropout", force=True, action="layout"))


def test_second_start_raises_while_running(tmp_path) -> None:
    _write_youtube_manifest(tmp_path)
    script = textwrap.dedent(
        """
        import signal, sys, time
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(130))
        time.sleep(30)
        """
    )

    async def run() -> None:
        runner = RunManager(tmp_path, command_factory=_factory(script))
        await runner.start("youtube")
        with pytest.raises(RuntimeError, match="already running"):
            await runner.start("youtube")
        await runner.stop()

    asyncio.run(run())


def test_start_after_natural_exit(tmp_path) -> None:
    _write_youtube_manifest(tmp_path)

    async def run() -> None:
        runner = RunManager(tmp_path, command_factory=_factory("print('done')"))
        await runner.start("youtube")
        await _wait_exited(runner)
        await runner.start("youtube")
        assert runner.snapshot()["status"] in {"running", "exited"}
        await _wait_exited(runner)

    asyncio.run(run())


def test_missing_manifest_raises(tmp_path) -> None:
    async def run() -> None:
        runner = RunManager(tmp_path)
        with pytest.raises(FileNotFoundError):
            await runner.start("youtube")

    asyncio.run(run())


def test_log_buffer_resets_sequence(tmp_path) -> None:
    _write_youtube_manifest(tmp_path)
    script = 'print("hello")\nprint("world")\n'

    async def run() -> None:
        runner = RunManager(tmp_path, command_factory=_factory(script))
        await runner.start("youtube")
        await _wait_exited(runner)
        lines = runner.lines_after(0)
        assert any("hello" in item.line for item in lines)
        first_max = max(item.n for item in lines)
        await runner.start("youtube")
        await _wait_exited(runner)
        second = runner.lines_after(0)
        assert second
        assert second[0].n == 1
        assert max(item.n for item in second) <= first_max

    asyncio.run(run())


def test_empty_log_lines_kept(tmp_path) -> None:
    _write_youtube_manifest(tmp_path)
    script = 'print("a")\nprint()\nprint("b")\n'

    async def run() -> None:
        runner = RunManager(tmp_path, command_factory=_factory(script))
        await runner.start("youtube")
        await _wait_exited(runner)
        lines = [item.line for item in runner.lines_after(0)]
        assert "a" in lines
        assert "" in lines
        assert "b" in lines

    asyncio.run(run())


def test_stop_sends_sigint(tmp_path) -> None:
    _write_youtube_manifest(tmp_path)
    script = textwrap.dedent(
        """
        import signal, sys, time
        def on_sig(signum, frame):
            sys.exit(130)
        signal.signal(signal.SIGINT, on_sig)
        time.sleep(60)
        """
    )

    async def run() -> None:
        runner = RunManager(tmp_path, command_factory=_factory(script))
        await runner.start("youtube")
        await runner.stop()
        snap = runner.snapshot()
        assert snap["status"] == "exited"
        assert snap["exit_code"] == 130

    asyncio.run(run())


def test_env_scrub_on_child(monkeypatch, tmp_path) -> None:
    _write_youtube_manifest(tmp_path)
    monkeypatch.setenv("YT_DLP_EMBY_VERBOSE", "1")
    captured: dict = {}

    def factory(*args, **kwargs):
        captured["argv"] = default_command(*args, **kwargs)
        return [sys.executable, "-c", "pass"]

    async def run() -> None:
        runner = RunManager(
            tmp_path,
            environ={**os.environ, "YT_DLP_EMBY_VERBOSE": "1"},
            command_factory=factory,
        )
        await runner.start("youtube", verbose=False)
        await asyncio.sleep(0.2)
        await runner.stop()

    asyncio.run(run())
    assert "--verbose" not in captured["argv"]


def test_download_passes_only_file(tmp_path) -> None:
    _write_youtube_manifest(tmp_path)
    plan = tmp_path / "plan.json"
    plan.write_text(
        '{"generated_at":"x","force":false,"sources":{"youtube":{"ok":true,"error":null,'
        '"seasons":[],"items":[{"id":"youtube|example-channel|S01E01","action":"download",'
        '"code":"S01E01","title":"A","dest_season":1,"season_title":null,"folder":"Season 1",'
        '"size":null,"series":"Example Channel","slug":"example-channel","platform":"youtube"}]}}}',
        encoding="utf-8",
    )
    def factory(source, manifest_path, **kwargs):
        return [sys.executable, "-c", "pass"]

    async def run() -> None:
        runner = RunManager(tmp_path, command_factory=factory)
        await runner.start_download(["youtube|example-channel|S01E01"])
        await _wait_exited(runner)
        only = tmp_path / "download-only.json"
        assert only.is_file()
        assert "youtube|example-channel|S01E01" in only.read_text(encoding="utf-8")

    asyncio.run(run())


def test_plan_runs_sequential_sources(tmp_path) -> None:
    _write_youtube_manifest(tmp_path)
    (tmp_path / "dropout.yaml").write_text(
        "library: /lib\nold_dir: /old\nseries:\n"
        "  - name: X\n    path: X\n    url: https://watch.dropout.tv/x\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    calls: list[str] = []

    def factory(source, manifest_path, **kwargs):
        calls.append(source)
        return [sys.executable, "-c", "print('ok')"]

    async def run() -> None:
        runner = RunManager(tmp_path, command_factory=factory)
        await runner.start_plan()
        await _wait_exited(runner)
        assert calls == ["dropout", "youtube"]

    asyncio.run(run())


def test_web_run_enables_color(tmp_path) -> None:
    _write_youtube_manifest(tmp_path)
    captured: dict = {}

    def factory(*args, **kwargs):
        captured["env"] = dict(os.environ)
        return [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('FORCE_COLOR', '')); "
            "print(os.environ.get('NO_COLOR', '<unset>'))",
        ]

    async def run() -> None:
        runner = RunManager(
            tmp_path,
            environ={**os.environ, "NO_COLOR": "1"},
            command_factory=factory,
        )
        await runner.start("youtube")
        await _wait_exited(runner)
        lines = [item.line for item in runner.lines_after(0)]
        assert lines[0] == "1"
        assert lines[1] == "<unset>"

    asyncio.run(run())


def test_event_sequence_survives_clear(tmp_path) -> None:
    runner = RunManager(tmp_path)
    runner._append_event({"event": "series", "name": "A"})
    assert runner.events_after(0)[0].n == 1
    runner._clear_events()
    runner._append_event({"event": "progress", "id": "dropout|x|S01E01", "percent": 12})
    fresh = runner.events_after(0)
    assert len(fresh) == 1
    assert fresh[0].n == 2
    assert runner.events_after(1)[0].event["percent"] == 12
    assert runner.snapshot()["progress"]["percent"] == 12


def test_events_poll_completes_partial_line(tmp_path) -> None:
    runner = RunManager(tmp_path)
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"event":"progress","id":"a","percent":')
    runner._poll_events_file()
    assert runner.events_after(0) == []
    path.write_bytes(path.read_bytes() + b"41}\n")
    runner._poll_events_file()
    events = runner.events_after(0)
    assert len(events) == 1
    assert events[0].event["percent"] == 41

