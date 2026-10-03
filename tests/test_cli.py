from pathlib import Path

import pytest

from yt_dlp_emby.cli import build_parser, main


def test_launcher_defaults(monkeypatch) -> None:
    monkeypatch.delenv("PORT", raising=False)
    args = build_parser().parse_args([])
    assert args.host == "127.0.0.1"
    assert args.port == 8080
    assert args.data_dir is None
    assert args.proxy_headers is False


@pytest.mark.parametrize("port", ["0", "65536", "invalid"])
def test_invalid_bind_port_rejected(port) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--port", port])
    assert exc.value.code == 2


@pytest.mark.parametrize("command", ["youtube", "dropout", "doctor", "bench", "server"])
def test_removed_public_commands_rejected(command) -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([command])
    assert exc.value.code == 2


def test_launcher_passes_bind_data_and_proxy_options(monkeypatch, tmp_path: Path) -> None:
    captured = {}
    monkeypatch.setattr("yt_dlp_emby.server.app.serve", lambda **kwargs: captured.update(kwargs))
    with pytest.raises(SystemExit) as exc:
        main(["--host", "0.0.0.0", "--port", "9000", "--data", str(tmp_path), "--proxy-headers"])
    assert exc.value.code == 0
    assert captured == {
        "host": "0.0.0.0",
        "port": 9000,
        "data_dir": tmp_path,
        "proxy_headers": True,
    }


def test_launcher_honors_port_and_proxy_environment(monkeypatch) -> None:
    monkeypatch.setenv("PORT", "9001")
    monkeypatch.setenv("YT_DLP_EMBY_PROXY_HEADERS", "true")
    captured = {}
    monkeypatch.setattr("yt_dlp_emby.server.app.serve", lambda **kwargs: captured.update(kwargs))
    with pytest.raises(SystemExit):
        main([])
    assert captured["port"] == 9001
    assert captured["proxy_headers"] is True
