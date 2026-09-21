from __future__ import annotations

import asyncio
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.register_assert_rewrite("yt_dlp_emby")

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return tmp_path


def write_youtube_manifest(data_dir: Path) -> Path:
    text = textwrap.dedent(
        f"""
        library: {data_dir / "lib"}
        old_dir: {data_dir / "old"}
        series:
          - name: Example Channel
            playlists:
              - url: https://www.youtube.com/playlist?list=PLaaaa
        """
    ).strip()
    path = data_dir / "youtube.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def write_dropout_manifest(data_dir: Path) -> Path:
    text = textwrap.dedent(
        f"""
        library: {data_dir / "lib"}
        old_dir: {data_dir / "old"}
        series:
          - name: Dimension 20
            path: Dimension 20
            url: https://watch.dropout.tv/example
            seasons:
              - dropout: 1
        """
    ).strip()
    path = data_dir / "dropout.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def youtube_manifest(data_dir: Path) -> Path:
    return write_youtube_manifest(data_dir)


@pytest.fixture
def dropout_manifest(data_dir: Path) -> Path:
    return write_dropout_manifest(data_dir)


def command_factory(script: str):
    return lambda *a, **k: [sys.executable, "-c", script]


def make_test_client(
    data_dir: Path,
    *,
    environ: dict[str, str] | None = None,
    command_factory=None,
    authed: bool = False,
):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from yt_dlp_emby.server.app import create_app

    client = TestClient(
        create_app(
            data_dir=data_dir,
            environ=environ or {},
            command_factory=command_factory,
        )
    )
    client.__enter__()
    if authed:
        response = client.post("/api/setup", json={"password": "secretpass"})
        assert response.status_code == 200, response.text
    return client


@pytest.fixture
def client(data_dir: Path) -> Iterator:
    instance = make_test_client(data_dir)
    try:
        yield instance
    finally:
        instance.__exit__(None, None, None)


@pytest.fixture
def authed_client(data_dir: Path) -> Iterator:
    instance = make_test_client(data_dir, authed=True)
    try:
        yield instance
    finally:
        instance.__exit__(None, None, None)


async def wait_exited(runner, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        snapshot = runner.snapshot()
        if snapshot["status"] == "exited":
            return
        await asyncio.sleep(0.05)
    lines = []
    dump = getattr(runner, "lines_after", None)
    if callable(dump):
        lines = dump(0)
    raise AssertionError(f"still {runner.snapshot()['status']}; log={lines!r}")
