"""FastAPI application for the optional web UI."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from yt_dlp_emby.config import (
    ConfigError,
    config_target_path,
    inspect_config_payload,
    write_config,
)
from yt_dlp_emby.cookies import (
    DEFAULT_COOKIE_FILES,
    confined_cookie_path,
    inspect_cookie_jars,
    write_cookie_jar,
)
from yt_dlp_emby.server.auth import AuthState, load_auth, setup_password, verify_password
from yt_dlp_emby.server.manifests import (
    ALLOWED,
    paths_from_text,
    read_manifest,
    validate_manifest_text,
    write_import,
    write_manifest,
)
from yt_dlp_emby.server.runner import CommandFactory, RunManager
from yt_dlp_emby.server.series import (
    add_series_source,
    create_series,
    delete_series,
    delete_series_source,
    get_series,
    list_series,
    list_series_episodes,
    patch_platform_cookies_field,
    platform_payload,
    put_platform,
    put_series,
    refresh_series_source,
)
from yt_dlp_emby.library import titles_match
from yt_dlp_emby.dropout_check import titles_related
from yt_dlp_emby.sonarr import fetch_episodes_cached
from yt_dlp_emby.config import load_config_values, config_target_path

LOG_POLL_SECONDS = 0.2
LOG_PING_SECONDS = 15.0

SESSION_KEY = "uid"
ADMIN_UID = "admin"
COOKIE_NAME = "yt_dlp_emby_session"
SESSION_MAX_AGE = 30 * 24 * 3600


class PasswordBody(BaseModel):
    password: str


class ManifestBody(BaseModel):
    text: str


class StartRunBody(BaseModel):
    source: str
    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    action: str = "download"


class ImportManifestBody(BaseModel):
    path: str
    text: str


class CookieBody(BaseModel):
    text: str


class ConfigBody(BaseModel):
    library: str | None = None
    old_dir: str | None = None
    staging: str | None = None
    bench_dest: str | None = None
    shows_dir: str | None = None
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None


class PlatformBody(BaseModel):
    library: str | None = None
    old_dir: str | None = None
    cookies: str | None = None


class CreateSeriesBody(BaseModel):
    name: str
    platform: str
    path: str
    tvdb_id: int | None = None


class SeriesPutBody(BaseModel):
    name: str
    path: str
    tvdb_id: int | None = None
    tvdb_skip: list[dict[str, Any]] | None = None
    sources: list[dict[str, Any]]


class AddSourceBody(BaseModel):
    url: str


class SonarrSuggestBody(BaseModel):
    tvdb_id: int
    title: str


def resolve_data_dir(data_dir: Path | None, environ: Mapping[str, str]) -> Path:
    if data_dir is not None:
        return data_dir
    env = environ.get("YT_DLP_EMBY_DATA", "").strip()
    if env:
        return Path(env)
    return Path.cwd()


def _static_dir(environ: Mapping[str, str]) -> Path | None:
    override = environ.get("YT_DLP_EMBY_WEB_DIST", "").strip()
    if override:
        path = Path(override)
        return path if path.is_dir() else None
    packaged = Path(__file__).parent / "static"
    return packaged if packaged.is_dir() else None


def _https_only(environ: Mapping[str, str]) -> bool:
    return environ.get("YT_DLP_EMBY_HTTPS", "").lower() in {"1", "true", "yes", "on"}


def _series_value_status(exc: BaseException) -> int:
    msg = str(exc)
    if "already exists" in msg or "ambiguous" in msg:
        return 409
    return 400


def create_app(
    data_dir: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    command_factory: CommandFactory | None = None,
) -> FastAPI:
    if environ is None:
        environ = os.environ
    resolved_data = resolve_data_dir(data_dir, environ)
    resolved_data.mkdir(parents=True, exist_ok=True)
    static_root = _static_dir(environ)
    initial_auth = load_auth(resolved_data, environ)

    runner = RunManager(
        resolved_data,
        environ=environ,
        command_factory=command_factory,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await runner.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.data_dir = resolved_data
    app.state.environ = environ
    app.state.auth = initial_auth
    app.state.runner = runner
    app.add_middleware(
        SessionMiddleware,
        secret_key=initial_auth.session_secret,
        session_cookie=COOKIE_NAME,
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=_https_only(environ),
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    def get_auth(request: Request) -> AuthState:
        return request.app.state.auth

    def get_runner(request: Request) -> RunManager:
        return request.app.state.runner

    def session_payload(request: Request) -> dict[str, bool]:
        auth = get_auth(request)
        authenticated = request.session.get(SESSION_KEY) == ADMIN_UID
        return {
            "setup_required": auth.setup_required,
            "authenticated": authenticated and not auth.setup_required,
        }

    def require_auth(request: Request) -> None:
        payload = session_payload(request)
        if payload["setup_required"] or not payload["authenticated"]:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "unauthorized",
                    "setup_required": payload["setup_required"],
                },
            )

    def manifest_json(payload: Any, request: Request) -> dict[str, Any]:
        return {
            "kind": payload.kind,
            "text": payload.text,
            "exists": payload.exists,
            "imports": [
                {"path": item.path, "text": item.text, "exists": item.exists}
                for item in payload.imports
            ],
            "paths": paths_from_text(
                payload.text,
                request.app.state.data_dir,
                request.app.state.environ,
            ),
        }

    @app.get("/api/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/session")
    async def session(request: Request) -> dict[str, bool]:
        return session_payload(request)

    @app.post("/api/setup")
    async def api_setup(body: PasswordBody, request: Request) -> JSONResponse:
        auth = get_auth(request)
        if not auth.setup_required:
            raise HTTPException(status_code=409, detail={"error": "already set up"})
        try:
            new_auth = await asyncio.to_thread(
                setup_password, request.app.state.data_dir, body.password, auth
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        request.app.state.auth = new_auth
        request.session[SESSION_KEY] = ADMIN_UID
        return JSONResponse({"ok": True})

    @app.post("/api/login")
    async def api_login(body: PasswordBody, request: Request) -> JSONResponse:
        auth = get_auth(request)
        if auth.setup_required:
            raise HTTPException(status_code=400, detail={"error": "setup required"})
        ok = await asyncio.to_thread(verify_password, body.password, auth)
        if not ok:
            raise HTTPException(status_code=401, detail={"error": "invalid password"})
        request.session[SESSION_KEY] = ADMIN_UID
        return JSONResponse({"ok": True})

    @app.post("/api/logout")
    async def api_logout(request: Request) -> dict[str, bool]:
        require_auth(request)
        request.session.clear()
        return {"ok": True}

    @app.get("/api/manifests/{kind}")
    async def get_manifest(kind: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        payload = read_manifest(request.app.state.data_dir, kind)
        return manifest_json(payload, request)

    @app.put("/api/manifests/{kind}")
    async def put_manifest(kind: str, body: ManifestBody, request: Request) -> JSONResponse:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        try:
            payload = write_manifest(request.app.state.data_dir, kind, body.text)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return JSONResponse(manifest_json(payload, request))

    @app.put("/api/manifests/{kind}/imports")
    async def put_manifest_import(
        kind: str, body: ImportManifestBody, request: Request
    ) -> JSONResponse:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        try:
            payload = write_import(
                request.app.state.data_dir, kind, body.path, body.text
            )
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return JSONResponse(
            {"path": payload.path, "text": payload.text, "exists": payload.exists}
        )

    @app.post("/api/manifests/{kind}/validate")
    async def validate_manifest(kind: str, body: ManifestBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        try:
            validate_manifest_text(request.app.state.data_dir, kind, body.text)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "ok": True,
            "paths": paths_from_text(
                body.text,
                request.app.state.data_dir,
                request.app.state.environ,
            ),
        }

    @app.get("/api/config")
    async def get_config(request: Request) -> dict[str, Any]:
        require_auth(request)
        return inspect_config_payload(
            environ=request.app.state.environ,
            cwd=request.app.state.data_dir,
        )

    @app.put("/api/config")
    async def put_config(body: ConfigBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        values = {
            "library": (body.library or "").strip() or None,
            "old_dir": (body.old_dir or "").strip() or None,
            "staging": (body.staging or "").strip() or None,
            "bench_dest": (body.bench_dest or "").strip() or None,
            "shows_dir": (body.shows_dir or "").strip() or None,
            "sonarr_url": (body.sonarr_url or "").strip() or None,
            "sonarr_api_key": (body.sonarr_api_key or "").strip() or None,
        }
        url = values["sonarr_url"]
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400,
                detail={"error": "sonarr_url must start with http:// or https://"},
            )
        path = config_target_path(
            None, request.app.state.environ, request.app.state.data_dir
        )
        try:
            await asyncio.to_thread(write_config, path, values)
        except OSError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return inspect_config_payload(
            environ=request.app.state.environ,
            cwd=request.app.state.data_dir,
        )

    @app.get("/api/cookies")
    async def get_cookies(request: Request) -> dict[str, Any]:
        require_auth(request)
        return inspect_cookie_jars(
            request.app.state.data_dir, request.app.state.environ
        )

    @app.put("/api/cookies/{kind}")
    async def put_cookies(kind: str, body: CookieBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        if kind not in DEFAULT_COOKIE_FILES:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        try:
            field = None
            from yt_dlp_emby.server.manifests import _manifest_path

            root = _manifest_path(request.app.state.data_dir, kind)
            if root.is_file():
                loaded = yaml.safe_load(root.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    field = loaded.get("cookies")
            written = await asyncio.to_thread(
                write_cookie_jar,
                request.app.state.data_dir,
                kind,
                body.text,
                filename=str(field) if field else None,
            )
            if confined_cookie_path(request.app.state.data_dir, str(field) if field else None) is None:
                if root.is_file():
                    await asyncio.to_thread(
                        patch_platform_cookies_field,
                        request.app.state.data_dir,
                        kind,
                        written.name,
                    )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except OSError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return inspect_cookie_jars(
            request.app.state.data_dir, request.app.state.environ
        )

    @app.get("/api/platform/{kind}")
    async def get_platform(kind: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        return platform_payload(
            request.app.state.data_dir, kind, request.app.state.environ
        )

    @app.put("/api/platform/{kind}")
    async def put_platform_route(
        kind: str, body: PlatformBody, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        try:
            return await asyncio.to_thread(
                put_platform,
                request.app.state.data_dir,
                kind,
                {
                    "library": body.library,
                    "old_dir": body.old_dir,
                    "cookies": body.cookies,
                },
                environ=request.app.state.environ,
            )
        except (ConfigError, ValueError) as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @app.get("/api/series")
    async def get_series_list(request: Request) -> dict[str, Any]:
        require_auth(request)
        return await asyncio.to_thread(list_series, request.app.state.data_dir)

    @app.post("/api/series")
    async def post_series(body: CreateSeriesBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                create_series,
                request.app.state.data_dir,
                request.app.state.environ,
                name=body.name,
                platform=body.platform,
                path=body.path,
                tvdb_id=body.tvdb_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    @app.get("/api/series/{platform}/{slug}")
    async def get_series_detail(
        platform: str, slug: str, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                get_series, request.app.state.data_dir, platform, slug
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    @app.put("/api/series/{platform}/{slug}")
    async def put_series_detail(
        platform: str, slug: str, body: SeriesPutBody, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        try:
            payload = body.model_dump()
            return await asyncio.to_thread(
                put_series, request.app.state.data_dir, platform, slug, payload
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    def _reject_if_run_active(request: Request) -> None:
        runner = get_runner(request)
        if runner.snapshot().get("status") in {"running", "stopping"}:
            raise HTTPException(
                status_code=409, detail={"error": "a run is in progress"}
            )

    @app.delete("/api/series/{platform}/{slug}")
    async def delete_series_route(
        platform: str, slug: str, request: Request
    ) -> Response:
        require_auth(request)
        try:
            await asyncio.to_thread(
                delete_series, request.app.state.data_dir, platform, slug
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc
        return Response(status_code=204)

    @app.post("/api/series/{platform}/{slug}/sources")
    async def post_series_source(
        platform: str, slug: str, body: AddSourceBody, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        _reject_if_run_active(request)
        try:
            return await asyncio.to_thread(
                add_series_source,
                request.app.state.data_dir,
                platform,
                slug,
                body.url,
                environ=request.app.state.environ,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    @app.delete("/api/series/{platform}/{slug}/sources/{source_id}")
    async def delete_series_source_route(
        platform: str, slug: str, source_id: int, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                delete_series_source,
                request.app.state.data_dir,
                platform,
                slug,
                source_id,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    @app.post("/api/series/{platform}/{slug}/sources/{source_id}/refresh")
    async def refresh_series_source_route(
        platform: str, slug: str, source_id: int, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        _reject_if_run_active(request)
        try:
            return await asyncio.to_thread(
                refresh_series_source,
                request.app.state.data_dir,
                platform,
                slug,
                source_id,
                environ=request.app.state.environ,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    @app.get(
        "/api/series/{platform}/{slug}/sources/{source_id}/seasons/{season_id}/episodes"
    )
    async def get_series_episodes(
        platform: str,
        slug: str,
        source_id: int,
        season_id: int,
        request: Request,
    ) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                list_series_episodes,
                request.app.state.data_dir,
                platform,
                slug,
                source_id,
                season_id,
                environ=request.app.state.environ,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    @app.get("/api/sonarr/episodes")
    async def get_sonarr_episodes(request: Request, tvdb_id: int) -> dict[str, Any]:
        require_auth(request)
        cfg_path = config_target_path(
            None, request.app.state.environ, request.app.state.data_dir
        )
        cfg = load_config_values(cfg_path) if cfg_path.is_file() else {}
        url = cfg.get("sonarr_url") or ""
        key = cfg.get("sonarr_api_key") or ""
        if not url or not key:
            raise HTTPException(
                status_code=400, detail={"error": "Sonarr is not configured"}
            )
        try:
            title, episodes = await asyncio.to_thread(
                fetch_episodes_cached,
                tvdb_id,
                base_url=url,
                api_key=key,
                cache_path=request.app.state.data_dir / "cache" / "sonarr.json",
            )
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "title": title,
            "episodes": [
                {
                    "season": ep.season,
                    "episode": ep.episode,
                    "title": ep.title,
                    "air_date": ep.air_date,
                }
                for ep in episodes
            ],
        }

    @app.post("/api/sonarr/suggest")
    async def post_sonarr_suggest(
        body: SonarrSuggestBody, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        cfg_path = config_target_path(
            None, request.app.state.environ, request.app.state.data_dir
        )
        cfg = load_config_values(cfg_path) if cfg_path.is_file() else {}
        url = cfg.get("sonarr_url") or ""
        key = cfg.get("sonarr_api_key") or ""
        if not url or not key:
            raise HTTPException(
                status_code=400, detail={"error": "Sonarr is not configured"}
            )
        try:
            _title, episodes = await asyncio.to_thread(
                fetch_episodes_cached,
                body.tvdb_id,
                base_url=url,
                api_key=key,
                cache_path=request.app.state.data_dir / "cache" / "sonarr.json",
            )
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        suggestions = [
            {
                "season": ep.season,
                "episode": ep.episode,
                "title": ep.title,
                "air_date": ep.air_date,
            }
            for ep in episodes
            if titles_match(ep.title, body.title) or titles_related(ep.title, body.title)
        ]
        return {"suggestions": suggestions[:20]}

    @app.get("/api/runs")
    async def get_runs(request: Request) -> dict[str, Any]:
        require_auth(request)
        return get_runner(request).snapshot()

    @app.post("/api/runs")
    async def post_runs(body: StartRunBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        runner = get_runner(request)
        if body.source not in ALLOWED:
            raise HTTPException(status_code=400, detail={"error": "unknown source"})
        if body.source == "youtube" and body.force:
            raise HTTPException(status_code=400, detail={"error": "force invalid for youtube"})
        action = body.action or "download"
        if body.source == "youtube" and action != "download":
            raise HTTPException(status_code=400, detail={"error": "action invalid for youtube"})
        if body.force and action != "download":
            raise HTTPException(status_code=400, detail={"error": "force invalid for layout or check"})
        manifest = request.app.state.data_dir / ALLOWED[body.source]
        if not manifest.is_file():
            raise HTTPException(status_code=400, detail={"error": "manifest not on disk"})
        try:
            await runner.start(
                body.source,
                dry_run=body.dry_run,
                verbose=body.verbose,
                force=body.force,
                action=action,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return runner.snapshot()

    @app.post("/api/runs/stop")
    async def post_runs_stop(request: Request) -> dict[str, Any]:
        require_auth(request)
        runner = get_runner(request)
        await runner.stop()
        return runner.snapshot()

    @app.get("/api/runs/log")
    async def runs_log(request: Request, after: int = 0) -> StreamingResponse:
        require_auth(request)
        runner = get_runner(request)

        async def event_stream() -> AsyncIterator[str]:
            last = after
            last_ping = asyncio.get_running_loop().time()
            yield ": connected\n\n"
            try:
                while True:
                    try:
                        disconnected = await asyncio.wait_for(
                            request.is_disconnected(), timeout=0.05
                        )
                    except TimeoutError:
                        disconnected = False
                    if disconnected:
                        break
                    for item in runner.lines_after(last):
                        payload = json.dumps({"n": item.n, "line": item.line})
                        yield f"data: {payload}\n\n"
                        last = item.n
                    now = asyncio.get_running_loop().time()
                    if now - last_ping >= LOG_PING_SECONDS:
                        yield ": ping\n\n"
                        last_ping = now
                    await asyncio.sleep(LOG_POLL_SECONDS)
            except asyncio.CancelledError:
                return

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    if static_root is not None:

        @app.get("/assets/{path:path}")
        async def assets(path: str) -> FileResponse:
            file_path = (static_root / "assets" / path).resolve()
            if not file_path.is_relative_to(static_root.resolve()):
                raise HTTPException(status_code=404)
            if not file_path.is_file():
                raise HTTPException(status_code=404)
            return FileResponse(
                file_path,
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )

        @app.get("/{full_path:path}")
        async def spa(full_path: str) -> Response:
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail={"error": "not found"})
            index = static_root / "index.html"
            if index.is_file():
                return FileResponse(
                    index,
                    headers={"Cache-Control": "no-store"},
                )
            raise HTTPException(status_code=404)

    else:

        @app.get("/")
        async def no_frontend() -> HTMLResponse:
            return HTMLResponse(
                "<p>Frontend not built. Run <code>pnpm dev</code> or <code>pnpm build</code>.</p>",
                status_code=503,
            )

    return app


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    data_dir: Path | None = None,
    proxy_headers: bool = False,
) -> None:
    import uvicorn

    app = create_app(data_dir=data_dir)
    uvicorn.run(
        app,
        host=host,
        port=port,
        workers=1,
        proxy_headers=proxy_headers,
    )
