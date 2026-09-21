import asyncio
import json
import sys
import textwrap
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

pytest.importorskip("fastapi")

from yt_dlp_emby.server.app import create_app, resolve_data_dir
from yt_dlp_emby.server.runner import CommandFactory

pytestmark = pytest.mark.web


def _factory(script: str) -> CommandFactory:
    return lambda *a, **k: [sys.executable, "-c", script]


@asynccontextmanager
async def _authed_async(tmp_path, command_factory=None) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        data_dir=tmp_path,
        environ={},
        command_factory=command_factory,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        setup = await client.post("/api/setup", json={"password": "secretpass"})
        assert setup.status_code == 200
        yield client


def _youtube_manifest(tmp_path) -> None:
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


def _dropout_manifest(tmp_path) -> None:
    text = textwrap.dedent(
        f"""
        library: {tmp_path / "lib"}
        old_dir: {tmp_path / "old"}
        series:
          - name: Dimension 20
            path: Dimension 20
            url: https://watch.dropout.tv/example
            seasons:
              - dropout: 1
        """
    ).strip()
    (tmp_path / "dropout.yaml").write_text(text, encoding="utf-8")


def _write_plan(tmp_path) -> None:
    plan = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "force": False,
        "sources": {
            "youtube": {
                "ok": True,
                "error": None,
                "seasons": [],
                "items": [
                    {
                        "id": "youtube|example-channel|S01E01",
                        "action": "download",
                        "code": "S01E01",
                        "title": "One",
                        "dest_season": 1,
                        "season_title": None,
                        "folder": "Season 1",
                        "size": None,
                        "series": "Example Channel",
                        "slug": "example-channel",
                        "platform": "youtube",
                    }
                ],
            }
        },
    }
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")


def test_health_unauthenticated(client) -> None:
    assert client.get("/api/health").json() == {"ok": True}


def test_download_without_plan_400(authed_client, tmp_path) -> None:
    client = authed_client
    _youtube_manifest(tmp_path)
    response = client.post("/api/runs", json={"ids": None})
    assert response.status_code == 400


def test_download_empty_ids_400(authed_client, tmp_path) -> None:
    client = authed_client
    _youtube_manifest(tmp_path)
    _write_plan(tmp_path)
    response = client.post("/api/runs", json={"ids": []})
    assert response.status_code == 400


async def test_http_plan_and_download(tmp_path) -> None:
    _youtube_manifest(tmp_path)

    async def run() -> None:
        async with _authed_async(tmp_path, _factory("print('ok', flush=True)")) as client:
            started = await client.post("/api/runs/plan", json={"force": False})
            assert started.status_code == 200
            body = started.json()
            assert body["phase"] == "planning" or body["status"] == "running"
            busy = await client.post("/api/runs/plan")
            assert busy.status_code == 409
            for _ in range(80):
                snap = (await client.get("/api/runs")).json()
                if snap["status"] == "exited":
                    break
                await asyncio.sleep(0.05)
            _write_plan(tmp_path)
            dl = await client.post("/api/runs", json={"ids": None})
            assert dl.status_code == 200
            assert dl.json()["phase"] in {"downloading", "running"}

    await run()


def test_get_plan_404(authed_client) -> None:
    client = authed_client
    assert client.get("/api/runs/plan").status_code == 404


def test_get_plan_ok(authed_client, tmp_path) -> None:
    client = authed_client
    _write_plan(tmp_path)
    body = client.get("/api/runs/plan").json()
    assert "sources" in body


async def test_http_start_stop_fake_child(tmp_path) -> None:
    _youtube_manifest(tmp_path)
    _write_plan(tmp_path)
    # Bounded wait (not sleep(30)): fail fast instead of pytest-timeout.
    script = textwrap.dedent(
        """
        import signal, sys, threading
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(130))
        print("started", flush=True)
        threading.Event().wait(15)
        """
    )

    async def run() -> None:
        async with _authed_async(tmp_path, _factory(script)) as client:
            started = await client.post("/api/runs", json={"ids": None})
            assert started.status_code == 200
            busy = await client.post("/api/runs", json={"ids": None})
            assert busy.status_code == 409
            stopped = await client.post("/api/runs/stop")
            assert stopped.status_code == 200
            assert stopped.json()["status"] == "exited"

    await run()


async def test_sse_emits_lines_quickly(tmp_path) -> None:
    import uvicorn

    _youtube_manifest(tmp_path)
    _write_plan(tmp_path)
    script = 'import time\nprint("hello", flush=True)\ntime.sleep(2)\n'
    app = create_app(
        data_dir=tmp_path,
        environ={},
        command_factory=_factory(script),
    )

    async def run() -> None:
        config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
        server = uvicorn.Server(config)
        serve_task = asyncio.create_task(server.serve())
        try:
            for _ in range(100):
                if server.started:
                    break
                await asyncio.sleep(0.05)
            assert server.started
            port = server.servers[0].sockets[0].getsockname()[1]
            t0 = time.monotonic()
            found = False
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
                setup = await client.post("/api/setup", json={"password": "secretpass"})
                assert setup.status_code == 200
                started = await client.post(
                    "/api/runs",
                    json={"ids": None},
                )
                assert started.status_code == 200
                async with client.stream("GET", "/api/runs/log?after=0") as response:
                    assert response.status_code == 200

                    async def read_until_hello() -> None:
                        nonlocal found
                        async for line in response.aiter_lines():
                            if "hello" in line:
                                found = True
                                return

                    await asyncio.wait_for(read_until_hello(), timeout=3)
                assert found
                assert time.monotonic() - t0 < 5
                await client.post("/api/runs/stop")
        finally:
            server.should_exit = True
            await asyncio.wait_for(serve_task, timeout=5)

    await run()


def test_api_404_not_spa(authed_client) -> None:
    client = authed_client
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404


def test_resolve_data_dir(tmp_path) -> None:
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    env_dir = tmp_path / "from-env"
    env_dir.mkdir()
    assert resolve_data_dir(None, {"YT_DLP_EMBY_DATA": str(env_dir)}) == env_dir
    assert resolve_data_dir(explicit, {"YT_DLP_EMBY_DATA": str(env_dir)}) == explicit


def test_openapi_core_paths_exist(client) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    for route in ("/api/session", "/api/runs", "/api/series"):
        assert route in paths, f"missing OpenAPI path {route}"
