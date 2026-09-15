import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from yt_dlp_emby.cli import build_parser


def test_youtube_rejects_server_flags() -> None:
    parser = build_parser()
    for flag in ("--data", "--host", "--port"):
        with pytest.raises(SystemExit):
            parser.parse_args(["youtube", flag, "x", "--library", "/l", "--old-dir", "/o"])


def test_subcommands_include_server() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(
        ["server", "--host", "127.0.0.1", "--port", "9000", "--data", "/tmp/data"]
    )
    assert args.command == "server"
    assert args.host == "127.0.0.1"
    assert args.port == 9000
    assert args.data_dir == "/tmp/data"


def test_server_default_host_and_port() -> None:
    args = build_parser().parse_args(["server"])
    assert args.host == "127.0.0.1"
    assert args.port == 8080
    assert args.data_dir is None


def test_cli_import_does_not_load_fastapi() -> None:
    script = (
        "import sys, yt_dlp_emby.cli; "
        "assert 'fastapi' not in sys.modules; "
        "assert 'uvicorn' not in sys.modules; "
        "assert 'yt_dlp_emby.server' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_server_missing_extra_hint(monkeypatch, capsys) -> None:
    import builtins
    from argparse import Namespace

    import yt_dlp_emby.cli as cli_mod

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "yt_dlp_emby.server.app":
            raise ImportError("no fastapi")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    args = Namespace(host="127.0.0.1", port=8080, data_dir=None, proxy_headers=False)
    code = cli_mod.run_server(args)
    assert code == 1
    assert "[server]" in capsys.readouterr().err


def test_core_deps_exclude_server_packages() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    core = " ".join(data["project"]["dependencies"]).lower()
    for pkg in ("fastapi", "uvicorn", "itsdangerous"):
        assert pkg not in core
    server = " ".join(data["project"]["optional-dependencies"]["server"]).lower()
    assert "fastapi" in server


def test_main_module_delegates() -> None:
    import yt_dlp_emby.__main__ as main_mod

    assert callable(main_mod.main)


def test_dropout_flags_unchanged() -> None:
    args = build_parser().parse_args(
        [
            "dropout",
            "download",
            "--manifest",
            "dropout.yaml",
            "--dry-run",
            "--verbose",
            "--force",
            "--create",
            "--series",
            "Dim",
            "--season",
            "1",
        ]
    )
    assert args.dry_run is True
    assert args.verbose is True
    assert args.force is True
    assert args.create is True
    assert args.series_filter == ["Dim"]
    assert args.season_filter == [1]
