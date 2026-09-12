"""FastAPI application for the optional web UI."""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Mapping

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.server.auth import AuthState, load_auth, setup_password, verify_password
from yt_dlp_emby.server.manifests import ALLOWED, read_manifest, write_manifest
from yt_dlp_emby.server.runner import CommandFactory, RunManager

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
        return {"kind": payload.kind, "text": payload.text, "exists": payload.exists}

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
        return JSONResponse(
            {"kind": payload.kind, "text": payload.text, "exists": payload.exists}
        )

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
        manifest = request.app.state.data_dir / ALLOWED[body.source]
        if not manifest.is_file():
            raise HTTPException(status_code=400, detail={"error": "manifest not on disk"})
        try:
            await runner.start(
                body.source,
                dry_run=body.dry_run,
                verbose=body.verbose,
                force=body.force,
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
