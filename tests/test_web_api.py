import asyncio
import sys
import textwrap
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app, resolve_data_dir
from yt_dlp_emby.server.runner import CommandFactory

pytestmark = pytest.mark.web


def _factory(script: str) -> CommandFactory:
    return lambda *a, **k: [sys.executable, "-c", script]


def _authed(tmp_path, command_factory=None) -> TestClient:
    client = TestClient(
        create_app(
            data_dir=tmp_path,
            environ={},
            command_factory=command_factory,
        )
    )
    client.post("/api/setup", json={"password": "secretpass"})
    return client


@asynccontextmanager
async def _authed_async(
    tmp_path, command_factory=None
) -> AsyncIterator[httpx.AsyncClient]:
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


START_BODY = {
    "source": "youtube",
    "dry_run": True,
    "verbose": False,
    "force": False,
}


def test_health_unauthenticated(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path, environ={}))
    assert client.get("/api/health").json() == {"ok": True}


def test_start_without_manifest_400(tmp_path) -> None:
    client = _authed(tmp_path)
    response = client.post("/api/runs", json=START_BODY)
    assert response.status_code == 400


def test_youtube_force_400(tmp_path) -> None:
    client = _authed(tmp_path)
    _youtube_manifest(tmp_path)
    response = client.post(
        "/api/runs",
        json={"source": "youtube", "dry_run": True, "verbose": False, "force": True},
    )
    assert response.status_code == 400


def test_http_start_stop_fake_child(tmp_path) -> None:
    _youtube_manifest(tmp_path)
    script = textwrap.dedent(
        """
        import signal, sys, time
        signal.signal(signal.SIGINT, lambda s, f: sys.exit(130))
        print("started", flush=True)
        time.sleep(30)
        """
    )

    async def run() -> None:
        async with _authed_async(tmp_path, _factory(script)) as client:
            started = await client.post("/api/runs", json=START_BODY)
            assert started.status_code == 200
            body = started.json()
            assert body["status"] == "running"
            assert body["source"] == "youtube"
            busy = await client.post("/api/runs", json=START_BODY)
            assert busy.status_code == 409
            stopped = await client.post("/api/runs/stop")
            assert stopped.status_code == 200
            assert stopped.json()["status"] == "exited"
            assert stopped.json()["exit_code"] == 130

    asyncio.run(run())


def test_http_start_after_natural_exit(tmp_path) -> None:
    _youtube_manifest(tmp_path)

    async def run() -> None:
        async with _authed_async(
            tmp_path, _factory("print('done', flush=True)")
        ) as client:
            first = await client.post("/api/runs", json=START_BODY)
            assert first.status_code == 200
            snap = first.json()
            for _ in range(80):
                snap = (await client.get("/api/runs")).json()
                if snap["status"] == "exited":
                    break
                await asyncio.sleep(0.05)
            assert snap["status"] == "exited"
            second = await client.post("/api/runs", json=START_BODY)
            assert second.status_code == 200

    asyncio.run(run())


def test_http_dropout_start(tmp_path) -> None:
    _dropout_manifest(tmp_path)

    async def run() -> None:
        async with _authed_async(tmp_path, _factory("print('ok')")) as client:
            response = await client.post(
                "/api/runs",
                json={
                    "source": "dropout",
                    "dry_run": True,
                    "verbose": False,
                    "force": True,
                },
            )
            assert response.status_code == 200
            assert response.json()["source"] == "dropout"
            assert response.json()["force"] is True

    asyncio.run(run())


def test_sse_emits_lines_quickly(tmp_path) -> None:
    import uvicorn

    _youtube_manifest(tmp_path)
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
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{port}"
            ) as client:
                setup = await client.post(
                    "/api/setup", json={"password": "secretpass"}
                )
                assert setup.status_code == 200
                started = await client.post(
                    "/api/runs",
                    json={
                        "source": "youtube",
                        "dry_run": False,
                        "verbose": False,
                        "force": False,
                    },
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

    asyncio.run(run())


def test_api_404_not_spa(tmp_path) -> None:
    client = _authed(tmp_path)
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404


def test_no_frontend_503(tmp_path) -> None:
    client = TestClient(
        create_app(
            data_dir=tmp_path,
            environ={"YT_DLP_EMBY_WEB_DIST": str(tmp_path / "missing-dist")},
        )
    )
    response = client.get("/")
    assert response.status_code == 503
    assert "pnpm" in response.text


def test_resolve_data_dir_env(tmp_path) -> None:
    env_dir = tmp_path / "from-env"
    assert resolve_data_dir(None, {"YT_DLP_EMBY_DATA": str(env_dir)}) == env_dir
    explicit = tmp_path / "explicit"
    assert resolve_data_dir(explicit, {"YT_DLP_EMBY_DATA": str(env_dir)}) == explicit


def test_cli_omits_data_so_env_can_apply() -> None:
    from yt_dlp_emby.cli import build_parser

    args = build_parser().parse_args(["server"])
    assert args.data_dir is None


def test_log_poll_is_subsecond() -> None:
    from yt_dlp_emby.server.app import LOG_POLL_SECONDS, LOG_PING_SECONDS

    assert LOG_POLL_SECONDS <= 0.25
    assert LOG_PING_SECONDS >= 5
