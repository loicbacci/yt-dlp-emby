from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import yt_dlp_emby.server.app as server_app
from yt_dlp_emby.server.app import SeriesRefreshBody, create_app

pytestmark = pytest.mark.web


@pytest.mark.asyncio
async def test_refresh_endpoint_persists_job_progress_and_result(
    monkeypatch, tmp_path: Path
) -> None:
    def refresh_batch(_data_dir, _items, *, on_progress, **_kwargs):
        on_progress({"completed": 1, "total": 1, "current": None})
        return {"ok": True, "results": [{"platform": "dropout", "slug": "show", "error": None}]}

    async def inline_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(server_app, "refresh_series_batch", refresh_batch)
    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)
    app = create_app(data_dir=tmp_path, environ={})

    async with app.router.lifespan_context(app):
        route = next(route for route in app.routes if route.path == "/api/series/refresh")
        response = await route.endpoint(
            SeriesRefreshBody(items=[{"platform": "dropout", "slug": "show"}]),
            SimpleNamespace(app=app),
            sync=False,
            _=None,
        )
        started = json.loads(response.body)
        assert response.status_code == 202
        active_route = next(
            route for route in app.routes if route.path == "/api/series/refresh/active"
        )
        active = await active_route.endpoint(SimpleNamespace(app=app), _=None)
        assert active["jobs"][0]["items"] == [{"platform": "dropout", "slug": "show"}]
        with pytest.raises(HTTPException, match="a manifest change or refresh is in progress"):
            await route.endpoint(
                SeriesRefreshBody(items=[{"platform": "dropout", "slug": "other"}]),
                SimpleNamespace(app=app),
                sync=False,
                _=None,
            )

        await asyncio.gather(*tuple(app.state.refresh_tasks))
        job = app.state.refresh_job_store.get(started["job_id"])
        assert job is not None
        assert job["status"] == "done"
        assert job["progress"]["completed"] == 1
        assert job["result"]["results"][0]["slug"] == "show"


@pytest.mark.asyncio
async def test_app_shutdown_waits_for_managed_refresh_tasks(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, environ={})
    lifespan = app.router.lifespan_context(app)
    await lifespan.__aenter__()
    started = asyncio.Event()
    release = asyncio.Event()

    async def pending_refresh() -> None:
        started.set()
        await release.wait()

    task = asyncio.create_task(pending_refresh())
    app.state.refresh_tasks.add(task)
    await started.wait()
    shutdown = asyncio.create_task(lifespan.__aexit__(None, None, None))
    await asyncio.sleep(0)
    assert not shutdown.done()

    release.set()
    await shutdown
    assert task.done()


@pytest.mark.asyncio
async def test_source_refresh_is_visible_as_active_until_manifest_merge_finishes(
    monkeypatch, tmp_path: Path
) -> None:
    app = create_app(data_dir=tmp_path, environ={})
    app.state.auth.setup_required = False
    app.state.auth.password_version = 1

    async def inline_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    def refresh_source(*_args, **_kwargs):
        assert app.state.manifest_refresh_active is True
        assert app.state.manifest_refresh_items == [{"platform": "dropout", "slug": "show"}]
        return {"slug": "show"}

    monkeypatch.setattr(asyncio, "to_thread", inline_to_thread)
    monkeypatch.setattr(server_app, "refresh_series_source", refresh_source)

    async with app.router.lifespan_context(app):
        route = next(
            route
            for route in app.routes
            if route.path == "/api/series/{platform}/{slug}/sources/{source_id}/refresh"
        )
        response = await route.endpoint(
            "dropout",
            "show",
            0,
            SimpleNamespace(app=app, session={"uid": "admin", "pv": 1}),
        )
        assert response == {"slug": "show"}
        assert app.state.manifest_refresh_active is False
        assert app.state.manifest_refresh_items == []
