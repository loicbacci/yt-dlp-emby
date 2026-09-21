"""FastAPI application for the optional web UI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import secrets
import time
from base64 import b64decode, b64encode
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Mapping
from urllib.parse import urlparse

import itsdangerous
import yaml
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from itsdangerous.exc import BadSignature
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import HTTPConnection
from starlette.types import Message, Receive, Scope, Send

from yt_dlp_emby.config import (
    ConfigError,
    config_target_path,
    env_value,
    inspect_config_payload,
    load_config_values,
    write_config,
)
from yt_dlp_emby.cookies import (
    DEFAULT_COOKIE_FILES,
    confined_cookie_path,
    inspect_cookie_jars,
    write_cookie_jar,
)
from yt_dlp_emby.dropout_check import titles_related
from yt_dlp_emby.library import titles_match
from yt_dlp_emby.server.auth import (
    AuthState,
    change_password,
    load_auth,
    setup_password,
    verify_password,
)
from yt_dlp_emby.server.manifests import (
    ALLOWED,
    paths_from_text,
    read_manifest,
    validate_manifest_text,
    write_import,
    write_manifest,
)
from yt_dlp_emby.server.plan_series import load_live_plan
from yt_dlp_emby.server.runner import ITEM_ID_PATTERN, CommandFactory, RunManager
from yt_dlp_emby.server.series import (
    AmbiguousSlugError,
    SeriesExistsError,
    add_series_source,
    create_series,
    delete_series,
    delete_series_source,
    dropout_series_check,
    dropout_series_layout,
    get_series,
    get_series_yaml,
    list_series,
    list_series_episodes,
    patch_platform_cookies_field,
    platform_payload,
    put_platform,
    put_series,
    put_series_yaml,
    refresh_series_batch,
    refresh_series_source,
    series_disk_status,
    series_missing_status,
    series_poster_bytes,
    validate_fs_dir_path,
)
from yt_dlp_emby.server.series_discover import sanitize_discovery_message
from yt_dlp_emby.sonarr import (
    assert_sonarr_url_allowed,
    fetch_episodes_cached,
    fetch_episodes_cached_meta,
    ping_sonarr,
)

logger = logging.getLogger("yt_dlp_emby.server")

LOG_POLL_SECONDS = 0.2
LOG_PING_SECONDS = 15.0

SESSION_KEY = "uid"
SESSION_PV_KEY = "pv"
ADMIN_UID = "admin"
COOKIE_NAME = "yt_dlp_emby_session"
# 7-day sliding window: the session cookie is re-signed on every response while
# the session is non-empty, so each authenticated request refreshes the expiry.
SESSION_MAX_AGE = 7 * 24 * 3600
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_REFRESH_ITEMS = 20
MAX_SSE_PER_IP = 5
SSE_MAX_SECONDS = 30 * 60
REFRESH_JOB_TTL_SECONDS = 3600.0
REFRESH_JOB_MAX_ENTRIES = 50
LOGIN_RATE = 5
LOGIN_WINDOW = 60.0
LOGIN_HOUR_RATE = 20
LOGIN_HOUR_WINDOW = 3600.0
OPEN_API_PATHS = frozenset({"/api/health", "/api/session", "/api/setup", "/api/login"})


class PasswordBody(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class ChangePasswordBody(BaseModel):
    current: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class ManifestBody(BaseModel):
    text: str = Field(max_length=2_000_000)


class PlanRunBody(BaseModel):
    force: bool = False


class DownloadRunBody(BaseModel):
    ids: list[Annotated[str, Field(pattern=ITEM_ID_PATTERN)]] | None = Field(
        default=None, max_length=500
    )
    force: bool = False


class ImportManifestBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    text: str = Field(max_length=2_000_000)


class CookieBody(BaseModel):
    text: str = Field(max_length=2_000_000)


class ConfigBody(BaseModel):
    library: str | None = Field(default=None, max_length=4096)
    old_dir: str | None = Field(default=None, max_length=4096)
    staging: str | None = Field(default=None, max_length=4096)
    bench_dest: str | None = Field(default=None, max_length=4096)
    shows_dir: str | None = Field(default=None, max_length=4096)
    sonarr_url: str | None = Field(default=None, max_length=2048)
    sonarr_api_key: str | None = Field(default=None, max_length=512)


class PlatformBody(BaseModel):
    library: str | None = Field(default=None, max_length=4096)
    old_dir: str | None = Field(default=None, max_length=4096)
    cookies: str | None = Field(default=None, max_length=512)


class CreateSeriesBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    platform: str = Field(min_length=1, max_length=32)
    path: str = Field(min_length=1, max_length=200)
    tvdb_id: int | None = Field(default=None, ge=1)


class RemapPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dropout_episode: int = Field(ge=1)
    skip: bool | None = None
    to_season: int | None = Field(default=None, ge=0)
    to_episode: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=500)


class SeasonPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, max_length=32)
    dropout: int | None = Field(default=None, ge=1)
    url: str | None = Field(default=None, max_length=2048)
    to_season: int | None = Field(default=None, ge=0)
    enabled: bool | None = None
    title: str | None = Field(default=None, max_length=500)
    only_episodes: list[int] | None = None
    remaps: list[RemapPut] | None = None
    skip_ids: list[str] | None = None
    label: str | None = Field(default=None, max_length=500)
    sublabel: str | None = Field(default=None, max_length=500)


class SeriesPutSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, max_length=32)
    url: str = Field(default="", max_length=2048)
    error: str | None = Field(default=None, max_length=2000)
    seasons: list[SeasonPut] = Field(default_factory=list)


class TvdbSkipPut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    season: int = Field(ge=0)
    episodes: list[int] = Field(default_factory=list)


class SeriesPutBody(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=200)
    tvdb_id: int | None = Field(default=None, ge=1)
    tvdb_skip: list[TvdbSkipPut] | None = None
    sources: list[SeriesPutSource]


class SeriesRefreshItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    platform: str = Field(min_length=1, max_length=32)
    slug: str = Field(min_length=1, max_length=200)


class SeriesRefreshBody(BaseModel):
    items: list[SeriesRefreshItem] = Field(max_length=MAX_REFRESH_ITEMS)
    parts: list[str] | None = None


class AddSourceBody(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class SonarrSuggestBody(BaseModel):
    tvdb_id: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=500)


class SonarrPingBody(BaseModel):
    sonarr_url: str | None = Field(default=None, max_length=2048)
    sonarr_api_key: str | None = Field(default=None, max_length=512)


class RotatingSecretSessionMiddleware(SessionMiddleware):
    """SessionMiddleware that tracks password rotations without a restart.

    Stock SessionMiddleware bakes the secret into a signer at startup, so a
    `change_password` rotation would leave old sessions valid until restart.
    This subclass re-reads `app.state.auth.session_secret` per request: the
    secret is resolved fresh both when unsigning the incoming cookie and when
    signing the outgoing one (the latter matters because rotation happens
    mid-request in POST /api/password). Old cookies fail `unsign` and yield an
    empty session, i.e. logout-all. Adapted from starlette's
    SessionMiddleware.__call__ — re-check against the vendored starlette
    version on upgrade.
    """

    def __init__(
        self,
        app: Any,
        secret_key: str,
        session_cookie: str = "session",
        max_age: int | None = 14 * 24 * 60 * 60,
        path: str = "/",
        same_site: str = "lax",
        https_only: bool = False,
        domain: str | None = None,
        httponly: bool = True,
    ) -> None:
        super().__init__(
            app,
            secret_key,
            session_cookie=session_cookie,
            max_age=max_age,
            path=path,
            same_site=same_site,  # type: ignore[arg-type]
            https_only=https_only,
            domain=domain,
        )
        self._fallback_secret = str(secret_key)
        if not httponly:
            self.security_flags = self.security_flags.replace("httponly; ", "")

    def _signer_for(self, scope: Scope) -> itsdangerous.TimestampSigner:
        try:
            secret = str(scope["app"].state.auth.session_secret)
        except (KeyError, AttributeError):
            secret = ""
        if not secret:
            secret = self._fallback_secret
        return itsdangerous.TimestampSigner(secret)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):  # pragma: no cover
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        initial_session_was_empty = True

        if self.session_cookie in connection.cookies:
            data = connection.cookies[self.session_cookie].encode("utf-8")
            try:
                data = self._signer_for(scope).unsign(data, max_age=self.max_age)
                scope["session"] = json.loads(b64decode(data))
                initial_session_was_empty = False
            except BadSignature:
                scope["session"] = {}
        else:
            scope["session"] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                if scope["session"]:
                    # We have session data to persist.
                    data = b64encode(json.dumps(scope["session"]).encode("utf-8"))
                    data = self._signer_for(scope).sign(data)
                    headers = MutableHeaders(scope=message)
                    header_value = (
                        "{session_cookie}={data}; path={path}; {max_age}{security_flags}".format(
                            session_cookie=self.session_cookie,
                            data=data.decode("utf-8"),
                            path=self.path,
                            max_age=f"Max-Age={self.max_age}; " if self.max_age else "",
                            security_flags=self.security_flags,
                        )
                    )
                    headers.append("Set-Cookie", header_value)
                elif not initial_session_was_empty:
                    # The session has been cleared.
                    headers = MutableHeaders(scope=message)
                    header_value = (
                        "{session_cookie}={data}; path={path}; {expires}{security_flags}".format(
                            session_cookie=self.session_cookie,
                            data="null",
                            path=self.path,
                            expires="expires=Thu, 01 Jan 1970 00:00:00 GMT; ",
                            security_flags=self.security_flags,
                        )
                    )
                    headers.append("Set-Cookie", header_value)
            await send(message)

        await self.app(scope, receive, send_wrapper)


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
    if environ.get("YT_DLP_EMBY_HTTPS", "").lower() in {"1", "true", "yes", "on"}:
        return True
    return bool(str(environ.get("TRUSTED_PROXY_IPS") or "").strip())


def _client_ip(request: Request) -> str:
    # TRUSTED_PROXY_IPS interplay: the login rate limiter (and audit logs) key
    # on request.client.host. serve() passes forwarded_allow_ips from
    # TRUSTED_PROXY_IPS to uvicorn, so with proxy_headers enabled the client IP
    # reflects the nearest untrusted X-Forwarded-For hop and cannot be spoofed
    # by outsiders. Without proxy_headers, X-Forwarded-For is ignored entirely
    # (direct peer only). If TRUSTED_PROXY_IPS is misconfigured, all users
    # behind the proxy share one rate-limit bucket (fail-closed: extra 429s).
    if request.client is not None and request.client.host:
        return request.client.host
    return "unknown"


def _request_is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    # Uvicorn (with proxy_headers) normally rewrites scope["scheme"] already;
    # honor the raw header too, but only when proxy headers are trusted, i.e.
    # TRUSTED_PROXY_IPS is configured (serve() enables proxy_headers then).
    forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if forwarded != "https":
        return False
    return bool(str(request.app.state.environ.get("TRUSTED_PROXY_IPS") or "").strip())


async def _failure_delay() -> None:
    await asyncio.sleep(random.uniform(0.05, 0.25))


def _csrf_ok(request: Request) -> bool:
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return True
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if not origin and not referer:
        return True
    host = request.headers.get("host", "")
    if not host:
        return False

    def _matches(value: str) -> bool:
        parsed = urlparse(value)
        return bool(parsed.netloc) and parsed.netloc == host

    if origin and not _matches(origin):
        return False
    if referer and not origin and not _matches(referer):
        return False
    return True


def _assert_safe_fs_path(
    value: str | None,
    name: str,
    *,
    data_dir: Path,
    environ: Mapping[str, str],
) -> None:
    try:
        validate_fs_dir_path(value, name, data_dir=data_dir, environ=environ)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc


def _mask_secret_value(value: Any) -> dict[str, Any]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return {"set": False, "masked": None}
    text = str(value)
    tail = text[-4:] if len(text) > 4 else text
    return {"set": True, "masked": f"****{tail}"}


def _mask_config_payload(payload: dict[str, Any], *, reveal: bool = False) -> dict[str, Any]:
    # Freshness note: ?reveal=1 requires a valid authenticated session (same
    # bar as every other config read); there is no additional step-up. That is
    # deemed acceptable for this single-admin app: anyone holding the session
    # cookie can already change the password.
    if reveal:
        return payload
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        return payload
    key_field = fields.get("sonarr_api_key")
    if isinstance(key_field, dict):
        masked = dict(key_field)
        for slot in ("file", "effective"):
            masked[slot] = _mask_secret_value(masked.get(slot))
        fields = dict(fields)
        fields["sonarr_api_key"] = masked
        payload = dict(payload)
        payload["fields"] = fields
    return payload


def _text_etag(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _series_value_status(exc: BaseException) -> int:
    """Typed mapping: Exists/Ambiguous → 409, everything else (incl. validation) → 400."""
    if isinstance(exc, (SeriesExistsError, AmbiguousSlugError)):
        return 409
    return 400


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _resolve_sonarr_credentials(
    *,
    environ: Mapping[str, str],
    data_dir: Path,
    sonarr_url: str | None = None,
    sonarr_api_key: str | None = None,
) -> tuple[str, str]:
    cfg_path = config_target_path(None, environ, data_dir)
    cfg = load_config_values(cfg_path) if cfg_path.is_file() else {}
    url = _first_text(
        sonarr_url,
        env_value(environ, "SONARR_URL"),
        cfg.get("sonarr_url"),
    )
    key = _first_text(
        sonarr_api_key,
        env_value(environ, "SONARR_API_KEY"),
        cfg.get("sonarr_api_key"),
    )
    return url, key


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
    app.state.refresh_jobs = {}
    app.state.manifest_lock = asyncio.Lock()
    app.state.login_hits = defaultdict(deque)
    app.state.sse_clients = defaultdict(int)

    def _error_body(detail: Any) -> dict[str, Any]:
        if isinstance(detail, dict):
            if "error" in detail:
                return detail
            return {"error": detail}
        return {"error": str(detail)}

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_error_body(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields: dict[str, str] = {}
        for error in exc.errors():
            loc = ".".join(
                str(part) for part in error.get("loc", ()) if part != "body" and part != ""
            )
            fields[loc or "body"] = str(error.get("msg", "invalid"))
        return JSONResponse(
            status_code=400, content={"error": "validation error", "fields": fields}
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content=_error_body(exc.detail))
        return JSONResponse(status_code=500, content={"error": "internal error"})

    def get_auth(request: Request) -> AuthState:
        return request.app.state.auth

    def get_runner(request: Request) -> RunManager:
        return request.app.state.runner

    @asynccontextmanager
    async def manifest_maintenance(request: Request) -> AsyncIterator[None]:
        """Serialize manifest/plan mutations; refuse them atomically during runs.

        The manifest lock serializes concurrent edits against each other while
        the runner maintenance hold (acquired atomically under the runner lock)
        409s when a run is active and blocks new run starts until released.
        """
        async with request.app.state.manifest_lock:
            runner = get_runner(request)
            acquired = await runner.try_acquire_maintenance()
            if not acquired:
                raise HTTPException(status_code=409, detail={"error": "a run is in progress"})
            try:
                yield
            finally:
                await runner.release_maintenance()

    def prune_refresh_jobs(request: Request) -> None:
        jobs = request.app.state.refresh_jobs
        now = time.monotonic()
        stale = [
            job_id
            for job_id, job in jobs.items()
            if now - float(job.get("created_at", now)) > REFRESH_JOB_TTL_SECONDS
        ]
        for job_id in stale:
            jobs.pop(job_id, None)
        while len(jobs) > REFRESH_JOB_MAX_ENTRIES:
            oldest = min(jobs, key=lambda jid: float(jobs[jid].get("created_at", 0.0)))
            jobs.pop(oldest, None)

    def session_payload(request: Request) -> dict[str, bool]:
        auth = get_auth(request)
        authenticated = request.session.get(SESSION_KEY) == ADMIN_UID
        # password_version rotates on every password change, so sessions that
        # predate a rotation are rejected here (logout-all) even if their
        # cookie signature is somehow still valid.
        version_ok = request.session.get(SESSION_PV_KEY) == auth.password_version
        return {
            "setup_required": auth.setup_required,
            "authenticated": authenticated and version_ok and not auth.setup_required,
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

    def _rate_limited(request: Request) -> tuple[bool, int]:
        """5/min + 20/hour per IP. Returns (limited, retry_after_seconds)."""
        ip = _client_ip(request)
        now = time.monotonic()
        hits: deque[float] = request.app.state.login_hits[ip]
        while hits and now - hits[0] > LOGIN_HOUR_WINDOW:
            hits.popleft()
        minute_hits = [ts for ts in hits if now - ts <= LOGIN_WINDOW]
        if len(minute_hits) >= LOGIN_RATE:
            retry = max(1, int(minute_hits[0] + LOGIN_WINDOW - now) + 1)
            return True, retry
        if len(hits) >= LOGIN_HOUR_RATE:
            retry = max(1, int(hits[0] + LOGIN_HOUR_WINDOW - now) + 1)
            return True, retry
        hits.append(now)
        return False, 0

    @app.middleware("http")
    async def security_stack(request: Request, call_next):  # type: ignore[no-untyped-def]
        length = request.headers.get("content-length")
        if length:
            try:
                if int(length) > MAX_BODY_BYTES:
                    return JSONResponse({"error": "payload too large"}, status_code=413)
            except ValueError:
                return JSONResponse({"error": "invalid content-length"}, status_code=400)
        if not _csrf_ok(request):
            return JSONResponse({"error": "csrf rejected"}, status_code=403)
        path = request.url.path
        if path in {"/api/login", "/api/setup"} and request.method == "POST":
            limited, retry_after = _rate_limited(request)
            if limited:
                return JSONResponse(
                    {"error": "too many attempts"},
                    status_code=429,
                    headers={"Retry-After": str(retry_after)},
                )
        if path.startswith("/api/") and path not in OPEN_API_PATHS:
            try:
                require_auth(request)
            except HTTPException as exc:
                return JSONResponse(status_code=exc.status_code, content=_error_body(exc.detail))
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        if _request_is_https(request) or _https_only(request.app.state.environ):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if _request_is_https(request):
            cookie = response.headers.get("set-cookie")
            if cookie and "secure" not in cookie.lower():
                response.headers["set-cookie"] = cookie + "; Secure"
        return response

    app.add_middleware(
        RotatingSecretSessionMiddleware,
        secret_key=initial_auth.session_secret,
        session_cookie=COOKIE_NAME,
        max_age=SESSION_MAX_AGE,
        same_site="lax",
        https_only=_https_only(environ),
        httponly=True,
    )
    # Host allowlist for Host-header attacks. Unset TRUSTED_HOSTS (default "*")
    # keeps single-host/test deployments working; set it (comma-separated, e.g.
    # "emby.lan,yt-emby.example.com") when serving a fixed public name.
    raw_hosts = str(environ.get("TRUSTED_HOSTS") or "").strip()
    allowed_hosts = [item.strip() for item in raw_hosts.split(",") if item.strip()] or ["*"]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

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

    @app.get("/api/health", tags=["health"], status_code=200, response_model=dict[str, bool])
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/session", tags=["auth"], status_code=200, response_model=dict[str, bool])
    async def session(request: Request) -> dict[str, bool]:
        return session_payload(request)

    @app.post("/api/setup", tags=["auth"], status_code=200)
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
        request.session.clear()
        request.session[SESSION_KEY] = ADMIN_UID
        request.session[SESSION_PV_KEY] = new_auth.password_version
        return JSONResponse({"ok": True})

    @app.post("/api/login", tags=["auth"], status_code=200)
    async def api_login(body: PasswordBody, request: Request) -> JSONResponse:
        auth = get_auth(request)
        if auth.setup_required:
            raise HTTPException(status_code=400, detail={"error": "setup required"})
        ok = await asyncio.to_thread(verify_password, body.password, auth)
        if not ok:
            await _failure_delay()
            raise HTTPException(status_code=401, detail={"error": "invalid password"})
        request.session.clear()
        request.session[SESSION_KEY] = ADMIN_UID
        request.session[SESSION_PV_KEY] = auth.password_version
        return JSONResponse({"ok": True})

    @app.post("/api/password", tags=["auth"], status_code=200)
    async def api_password(body: ChangePasswordBody, request: Request) -> JSONResponse:
        require_auth(request)
        auth = get_auth(request)
        try:
            new_auth = await asyncio.to_thread(
                change_password,
                request.app.state.data_dir,
                body.current,
                body.password,
                auth,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        request.app.state.auth = new_auth
        request.session.clear()
        request.session[SESSION_KEY] = ADMIN_UID
        request.session[SESSION_PV_KEY] = new_auth.password_version
        logger.info("password changed by %s (sessions rotated)", _client_ip(request))
        return JSONResponse({"ok": True})

    @app.post("/api/logout", tags=["auth"], status_code=200, response_model=dict[str, bool])
    async def api_logout(request: Request) -> dict[str, bool]:
        require_auth(request)
        request.session.clear()
        return {"ok": True}

    @app.get("/api/manifests/{kind}", tags=["manifests"], status_code=200)
    async def get_manifest(kind: str, request: Request) -> JSONResponse:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        payload = await asyncio.to_thread(read_manifest, request.app.state.data_dir, kind)
        body = await asyncio.to_thread(manifest_json, payload, request)
        etag = _text_etag(payload.text)
        response = JSONResponse(body)
        response.headers["ETag"] = f'"{etag}"'
        return response

    @app.put("/api/manifests/{kind}", tags=["manifests"], status_code=200)
    async def put_manifest(kind: str, body: ManifestBody, request: Request) -> JSONResponse:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        async with manifest_maintenance(request):
            current = await asyncio.to_thread(read_manifest, request.app.state.data_dir, kind)
            if_match = request.headers.get("if-match")
            if if_match:
                expected = if_match.strip().strip('"')
                actual = _text_etag(current.text)
                if expected != actual:
                    from yt_dlp_emby.log import warn

                    warn(f"If-Match mismatch for {kind} manifest (continuing)")
            try:
                payload = await asyncio.to_thread(
                    write_manifest, request.app.state.data_dir, kind, body.text
                )
            except ConfigError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            return JSONResponse(await asyncio.to_thread(manifest_json, payload, request))

    @app.put("/api/manifests/{kind}/imports", tags=["manifests"], status_code=200)
    async def put_manifest_import(
        kind: str, body: ImportManifestBody, request: Request
    ) -> JSONResponse:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        async with manifest_maintenance(request):
            try:
                payload = await asyncio.to_thread(
                    write_import, request.app.state.data_dir, kind, body.path, body.text
                )
            except ConfigError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            return JSONResponse(
                {"path": payload.path, "text": payload.text, "exists": payload.exists}
            )

    @app.put(
        "/api/manifests/{kind}/imports/{import_path:path}", tags=["manifests"], status_code=200
    )
    async def put_manifest_import_path(
        kind: str, import_path: str, body: ManifestBody, request: Request
    ) -> JSONResponse:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        async with manifest_maintenance(request):
            try:
                payload = await asyncio.to_thread(
                    write_import, request.app.state.data_dir, kind, import_path, body.text
                )
            except ConfigError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            return JSONResponse(
                {"path": payload.path, "text": payload.text, "exists": payload.exists}
            )

    @app.post(
        "/api/manifests/{kind}/validate",
        tags=["manifests"],
        status_code=200,
        response_model=dict[str, Any],
    )
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

    @app.get("/api/config", tags=["config"], status_code=200, response_model=dict[str, Any])
    async def get_config(
        request: Request, reveal: bool = False, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        if reveal:
            logger.info("config secrets revealed by %s", _client_ip(request))
        return _mask_config_payload(
            inspect_config_payload(
                environ=request.app.state.environ,
                cwd=request.app.state.data_dir,
            ),
            reveal=reveal,
        )

    @app.put("/api/config", tags=["config"], status_code=200, response_model=dict[str, Any])
    async def put_config(
        body: ConfigBody, request: Request, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        values = {
            "library": (body.library or "").strip() or None,
            "old_dir": (body.old_dir or "").strip() or None,
            "staging": (body.staging or "").strip() or None,
            "bench_dest": (body.bench_dest or "").strip() or None,
            "shows_dir": (body.shows_dir or "").strip() or None,
            "sonarr_url": (body.sonarr_url or "").strip() or None,
            "sonarr_api_key": (body.sonarr_api_key or "").strip() or None,
        }
        data_dir = request.app.state.data_dir
        environ = request.app.state.environ
        _assert_safe_fs_path(values["library"], "library", data_dir=data_dir, environ=environ)
        _assert_safe_fs_path(values["old_dir"], "old_dir", data_dir=data_dir, environ=environ)
        _assert_safe_fs_path(values["staging"], "staging", data_dir=data_dir, environ=environ)
        _assert_safe_fs_path(values["bench_dest"], "bench_dest", data_dir=data_dir, environ=environ)
        _assert_safe_fs_path(values["shows_dir"], "shows_dir", data_dir=data_dir, environ=environ)
        url = values["sonarr_url"]
        if url:
            if not url.startswith(("http://", "https://")):
                raise HTTPException(
                    status_code=400,
                    detail={"error": "sonarr_url must start with http:// or https://"},
                )
            try:
                assert_sonarr_url_allowed(url, environ=request.app.state.environ)
            except ConfigError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        path = config_target_path(None, request.app.state.environ, request.app.state.data_dir)
        try:
            await asyncio.to_thread(write_config, path, values)
        except (OSError, ConfigError) as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        # Audit: field names only, never values (sonarr_api_key is secret).
        touched = sorted(key for key, val in values.items() if val)
        logger.info("config updated by %s: fields=%s", _client_ip(request), ",".join(touched))
        return _mask_config_payload(
            inspect_config_payload(
                environ=request.app.state.environ,
                cwd=request.app.state.data_dir,
            )
        )

    @app.get("/api/cookies", tags=["config"], status_code=200, response_model=dict[str, Any])
    async def get_cookies(request: Request) -> dict[str, Any]:
        require_auth(request)
        return await asyncio.to_thread(
            inspect_cookie_jars, request.app.state.data_dir, request.app.state.environ
        )

    @app.put("/api/cookies/{kind}", tags=["config"], status_code=200, response_model=dict[str, Any])
    async def put_cookies(kind: str, body: CookieBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        if kind not in DEFAULT_COOKIE_FILES:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        try:
            field = None
            from yt_dlp_emby.server.manifests import _manifest_path

            root = _manifest_path(request.app.state.data_dir, kind)
            if await asyncio.to_thread(root.is_file):
                loaded = yaml.safe_load(await asyncio.to_thread(root.read_text, encoding="utf-8"))
                if isinstance(loaded, dict):
                    field = loaded.get("cookies")
            written = await asyncio.to_thread(
                write_cookie_jar,
                request.app.state.data_dir,
                kind,
                body.text,
                filename=str(field) if field else None,
            )
            if (
                confined_cookie_path(request.app.state.data_dir, str(field) if field else None)
                is None
            ):
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
        return await asyncio.to_thread(
            inspect_cookie_jars, request.app.state.data_dir, request.app.state.environ
        )

    @app.get(
        "/api/platform/{kind}", tags=["config"], status_code=200, response_model=dict[str, Any]
    )
    async def get_platform(kind: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        return await asyncio.to_thread(
            platform_payload, request.app.state.data_dir, kind, request.app.state.environ
        )

    @app.put(
        "/api/platform/{kind}", tags=["config"], status_code=200, response_model=dict[str, Any]
    )
    async def put_platform_route(kind: str, body: PlatformBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        if kind not in ALLOWED:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        # No run guard by design: the CLI child resolves library/old_dir/cookies
        # once at spawn, and YAML saves are atomic renames, so a mid-run edit
        # can neither corrupt the running job nor be torn for the next one.
        # The manifest lock still serializes this against other YAML writers.
        async with request.app.state.manifest_lock:
            try:
                result = await asyncio.to_thread(
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
        touched = sorted(
            key
            for key, val in (
                ("library", body.library),
                ("old_dir", body.old_dir),
                ("cookies", body.cookies),
            )
            if val
        )
        logger.info(
            "platform %s updated by %s: fields=%s",
            kind,
            _client_ip(request),
            ",".join(touched),
        )
        return result

    @app.get("/api/series", tags=["series"], status_code=200, response_model=dict[str, Any])
    async def get_series_list(request: Request) -> dict[str, Any]:
        require_auth(request)
        return await asyncio.to_thread(
            list_series,
            request.app.state.data_dir,
            request.app.state.environ,
        )

    @app.get(
        "/api/series/refresh/{job_id}",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def get_series_refresh_job(
        job_id: str, request: Request, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        prune_refresh_jobs(request)
        job = request.app.state.refresh_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        return job

    @app.post("/api/series", tags=["series"], status_code=200, response_model=dict[str, Any])
    async def post_series(
        body: CreateSeriesBody, request: Request, _: None = Depends(require_auth)
    ) -> dict[str, Any]:
        async with manifest_maintenance(request):
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
            except SeriesExistsError as exc:
                raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=_series_value_status(exc), detail={"error": str(exc)}
                ) from exc

    @app.get(
        "/api/series/dropout/{slug}/layout",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def get_dropout_layout(slug: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                dropout_series_layout,
                request.app.state.data_dir,
                request.app.state.environ,
                slug,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @app.get(
        "/api/series/dropout/{slug}/check",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def get_dropout_check(slug: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                dropout_series_check,
                request.app.state.data_dir,
                request.app.state.environ,
                slug,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @app.get(
        "/api/series/{platform}/{slug}",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def get_series_detail(platform: str, slug: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(get_series, request.app.state.data_dir, platform, slug)
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    @app.get("/api/series/{platform}/{slug}/poster", tags=["series"], status_code=200)
    async def get_series_poster(platform: str, slug: str, request: Request) -> Response:
        require_auth(request)
        try:
            data = await asyncio.to_thread(
                series_poster_bytes,
                request.app.state.data_dir,
                platform,
                slug,
                environ=request.app.state.environ,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ConfigError:
            raise HTTPException(status_code=404, detail={"error": "no poster"})
        if not data:
            raise HTTPException(status_code=404, detail={"error": "no poster"})
        etag = f'"{hashlib.sha256(data).hexdigest()}"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304)
        return Response(
            content=data,
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600", "ETag": etag},
        )

    @app.get("/api/series/{platform}/{slug}/yaml", tags=["series"], status_code=200)
    async def get_series_yaml_route(platform: str, slug: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                get_series_yaml, request.app.state.data_dir, platform, slug
            )
        except KeyError:
            raise HTTPException(status_code=404, detail={"error": "not found"})
        except ValueError as exc:
            raise HTTPException(
                status_code=_series_value_status(exc), detail={"error": str(exc)}
            ) from exc

    @app.put("/api/series/{platform}/{slug}/yaml", tags=["series"], status_code=200)
    async def put_series_yaml_route(
        platform: str,
        slug: str,
        body: ManifestBody,
        request: Request,
        _: None = Depends(require_auth),
    ) -> dict[str, Any]:
        async with manifest_maintenance(request):
            try:
                return await asyncio.to_thread(
                    put_series_yaml,
                    request.app.state.data_dir,
                    platform,
                    slug,
                    body.text,
                    environ=request.app.state.environ,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail={"error": "not found"})
            except SeriesExistsError as exc:
                raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
            except (ConfigError, ValueError) as exc:
                raise HTTPException(
                    status_code=_series_value_status(exc), detail={"error": str(exc)}
                ) from exc

    @app.post("/api/series/refresh", tags=["series"], status_code=200)
    async def post_series_refresh(
        body: SeriesRefreshBody,
        request: Request,
        background_tasks: BackgroundTasks,
        sync: bool = False,
        _: None = Depends(require_auth),
    ) -> Any:
        if not body.items:
            raise HTTPException(status_code=400, detail={"error": "empty items"})
        if len(body.items) > MAX_REFRESH_ITEMS:
            raise HTTPException(status_code=400, detail={"error": "too many items"})
        items = [item.model_dump() for item in body.items]

        def _run() -> dict[str, Any]:
            return refresh_series_batch(
                request.app.state.data_dir,
                items,
                environ=request.app.state.environ,
                parts=body.parts,
            )

        if sync:
            async with manifest_maintenance(request):
                return await asyncio.to_thread(_run)
        # Async path: acquire both locks up front (409 now when a run is
        # active) and hold them until the background job finishes, so the
        # refresh is atomic against concurrent edits and run starts.
        prune_refresh_jobs(request)
        await request.app.state.manifest_lock.acquire()
        try:
            acquired = await get_runner(request).try_acquire_maintenance()
        except Exception:
            request.app.state.manifest_lock.release()
            raise
        if not acquired:
            request.app.state.manifest_lock.release()
            raise HTTPException(status_code=409, detail={"error": "a run is in progress"})
        job_id = secrets.token_hex(8)
        request.app.state.refresh_jobs[job_id] = {
            "status": "running",
            "result": None,
            "error": None,
            "created_at": time.monotonic(),
        }

        async def _job() -> None:
            try:
                result = await asyncio.to_thread(_run)
                request.app.state.refresh_jobs[job_id] = {
                    "status": "done",
                    "result": result,
                    "error": None,
                    "created_at": time.monotonic(),
                }
            except Exception as exc:
                logger.exception("series refresh job %s failed", job_id)
                request.app.state.refresh_jobs[job_id] = {
                    "status": "error",
                    "result": None,
                    "error": str(exc),
                    "created_at": time.monotonic(),
                }
            finally:
                await get_runner(request).release_maintenance()
                request.app.state.manifest_lock.release()

        background_tasks.add_task(_job)
        return JSONResponse({"job_id": job_id, "status": "running"}, status_code=202)

    @app.put(
        "/api/series/{platform}/{slug}",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def put_series_detail(
        platform: str,
        slug: str,
        body: SeriesPutBody,
        request: Request,
        _: None = Depends(require_auth),
    ) -> dict[str, Any]:
        async with manifest_maintenance(request):
            try:
                payload = body.model_dump()
                return await asyncio.to_thread(
                    put_series,
                    request.app.state.data_dir,
                    platform,
                    slug,
                    payload,
                    environ=request.app.state.environ,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail={"error": "not found"})
            except SeriesExistsError as exc:
                raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(
                    status_code=_series_value_status(exc), detail={"error": str(exc)}
                ) from exc

    @app.delete("/api/series/{platform}/{slug}", tags=["series"], status_code=204)
    async def delete_series_route(platform: str, slug: str, request: Request) -> Response:
        require_auth(request)
        async with manifest_maintenance(request):
            try:
                await asyncio.to_thread(delete_series, request.app.state.data_dir, platform, slug)
            except KeyError:
                raise HTTPException(status_code=404, detail={"error": "not found"})
            except ValueError as exc:
                raise HTTPException(
                    status_code=_series_value_status(exc), detail={"error": str(exc)}
                ) from exc
        return Response(status_code=204)

    @app.post(
        "/api/series/{platform}/{slug}/sources",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def post_series_source(
        platform: str, slug: str, body: AddSourceBody, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        async with manifest_maintenance(request):
            try:
                from yt_dlp_emby.server.series_discover import assert_public_catalog_url

                # Accepted risk (DNS rebinding TOCTOU): the URL is resolved once
                # here to reject private/reserved IPs, but yt-dlp re-resolves at
                # fetch time, so pinning is infeasible. Redirects to private IPs
                # during yt-dlp-driven discovery are not guarded either; only the
                # server's own image fetches enforce redirect guards.
                assert_public_catalog_url(body.url)
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
                    status_code=_series_value_status(exc),
                    detail={"error": sanitize_discovery_message(str(exc), limit=500)},
                ) from exc

    @app.delete(
        "/api/series/{platform}/{slug}/sources/{source_id}",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def delete_series_source_route(
        platform: str, slug: str, source_id: int, request: Request
    ) -> dict[str, Any]:
        # Deviation from "DELETE is 204-empty": the web client
        # (deleteSeriesSource in web/src/api.ts) parses the updated SeriesDetail
        # from the response body, so this keeps returning 200 + body.
        require_auth(request)
        async with manifest_maintenance(request):
            try:
                return await asyncio.to_thread(
                    delete_series_source,
                    request.app.state.data_dir,
                    platform,
                    slug,
                    source_id,
                    environ=request.app.state.environ,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail={"error": "not found"})
            except ValueError as exc:
                raise HTTPException(
                    status_code=_series_value_status(exc), detail={"error": str(exc)}
                ) from exc

    @app.post(
        "/api/series/{platform}/{slug}/sources/{source_id}/refresh",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def refresh_series_source_route(
        platform: str, slug: str, source_id: int, request: Request
    ) -> dict[str, Any]:
        require_auth(request)
        async with manifest_maintenance(request):
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
                    status_code=_series_value_status(exc),
                    detail={"error": sanitize_discovery_message(str(exc), limit=500)},
                ) from exc

    @app.get(
        "/api/series/{platform}/{slug}/disk",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def get_series_disk(platform: str, slug: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                series_disk_status,
                request.app.state.data_dir,
                platform,
                slug,
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
        "/api/series/{platform}/{slug}/missing",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def get_series_missing(platform: str, slug: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                series_missing_status,
                request.app.state.data_dir,
                platform,
                slug,
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
        "/api/series/{platform}/{slug}/sources/{source_id}/seasons/{season_id}/episodes",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
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

    @app.post("/api/sonarr/ping", tags=["sonarr"], status_code=200, response_model=dict[str, Any])
    async def post_sonarr_ping(body: SonarrPingBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        url, key = _resolve_sonarr_credentials(
            environ=request.app.state.environ,
            data_dir=request.app.state.data_dir,
            sonarr_url=body.sonarr_url,
            sonarr_api_key=body.sonarr_api_key,
        )
        if not url or not key:
            raise HTTPException(
                status_code=400,
                detail={"error": "Sonarr URL and API key are required"},
            )
        if not url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400,
                detail={"error": "sonarr_url must start with http:// or https://"},
            )
        try:
            assert_sonarr_url_allowed(url, environ=request.app.state.environ)
            return await asyncio.to_thread(ping_sonarr, base_url=url, api_key=key)
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc

    @app.get(
        "/api/sonarr/episodes", tags=["sonarr"], status_code=200, response_model=dict[str, Any]
    )
    async def get_sonarr_episodes(request: Request, tvdb_id: int = Query(ge=1)) -> dict[str, Any]:
        require_auth(request)
        url, key = _resolve_sonarr_credentials(
            environ=request.app.state.environ,
            data_dir=request.app.state.data_dir,
        )
        if not url or not key:
            raise HTTPException(status_code=400, detail={"error": "Sonarr is not configured"})
        if not url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400,
                detail={"error": "sonarr_url must start with http:// or https://"},
            )
        try:
            title, episodes, title_slug = await asyncio.to_thread(
                fetch_episodes_cached_meta,
                tvdb_id,
                base_url=url,
                api_key=key,
                cache_path=request.app.state.data_dir / "cache" / "sonarr.json",
            )
        except ConfigError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return {
            "title": title,
            "title_slug": title_slug,
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

    @app.post(
        "/api/sonarr/suggest", tags=["sonarr"], status_code=200, response_model=dict[str, Any]
    )
    async def post_sonarr_suggest(body: SonarrSuggestBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        url, key = _resolve_sonarr_credentials(
            environ=request.app.state.environ,
            data_dir=request.app.state.data_dir,
        )
        if not url or not key:
            raise HTTPException(status_code=400, detail={"error": "Sonarr is not configured"})
        if not url.startswith(("http://", "https://")):
            raise HTTPException(
                status_code=400,
                detail={"error": "sonarr_url must start with http:// or https://"},
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

    @app.get("/api/runs", tags=["runs"], status_code=200, response_model=dict[str, Any])
    async def get_runs(request: Request) -> dict[str, Any]:
        require_auth(request)
        runner = get_runner(request)
        return await asyncio.to_thread(runner.snapshot)

    @app.get("/api/plans/latest", tags=["plans"], status_code=200, response_model=dict[str, Any])
    async def get_plans_latest(request: Request) -> dict[str, Any]:
        require_auth(request)
        plan = await asyncio.to_thread(
            load_live_plan, request.app.state.data_dir, request.app.state.environ
        )
        if plan is None:
            raise HTTPException(status_code=404, detail={"error": "no plan"})
        return plan

    @app.get("/api/runs/plan", tags=["runs"], status_code=200, deprecated=True)
    async def get_runs_plan(request: Request) -> dict[str, Any]:
        # Deprecated alias of GET /api/plans/latest; the SPA still calls this.
        return await get_plans_latest(request)

    @app.get("/api/plan", tags=["runs"], status_code=200, deprecated=True)
    async def get_plan_alias(request: Request) -> dict[str, Any]:
        # Deprecated alias of GET /api/plans/latest; the SPA still calls this.
        return await get_plans_latest(request)

    @app.post("/api/plans", tags=["plans"], status_code=200, response_model=dict[str, Any])
    async def post_plans(request: Request, body: PlanRunBody | None = None) -> dict[str, Any]:
        require_auth(request)
        runner = get_runner(request)
        force = body.force if body is not None else False
        try:
            await runner.start_plan(force=force)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return await asyncio.to_thread(runner.snapshot)

    @app.post("/api/runs/plan", tags=["runs"], status_code=200, deprecated=True)
    async def post_runs_plan(request: Request, body: PlanRunBody | None = None) -> dict[str, Any]:
        # Deprecated alias of POST /api/plans; the SPA still calls this.
        return await post_plans(request, body)

    @app.post("/api/runs", tags=["runs"], status_code=200, response_model=dict[str, Any])
    async def post_runs(body: DownloadRunBody, request: Request) -> dict[str, Any]:
        require_auth(request)
        if body.ids is not None and len(body.ids) == 0:
            raise HTTPException(status_code=400, detail={"error": "empty download selection"})
        runner = get_runner(request)
        try:
            await runner.start_download(body.ids, force=body.force)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
        return await asyncio.to_thread(runner.snapshot)

    @app.post("/api/runs/stop", tags=["runs"], status_code=200, response_model=dict[str, Any])
    async def post_runs_stop(request: Request) -> dict[str, Any]:
        require_auth(request)
        runner = get_runner(request)
        await runner.stop()
        return await asyncio.to_thread(runner.snapshot)

    @app.get("/api/runs/log", tags=["runs"], status_code=200)
    async def runs_log(
        request: Request, after: int = Query(default=0, ge=0, le=10000)
    ) -> StreamingResponse:
        require_auth(request)
        runner = get_runner(request)
        ip = _client_ip(request)
        if request.app.state.sse_clients[ip] >= MAX_SSE_PER_IP:
            raise HTTPException(status_code=429, detail={"error": "too many streams"})
        request.app.state.sse_clients[ip] += 1

        async def event_stream() -> AsyncIterator[str]:
            last = after
            loop = asyncio.get_running_loop()
            started = loop.time()
            last_ping = started
            yield ": connected\n\n"
            try:
                while True:
                    if loop.time() - started > SSE_MAX_SECONDS:
                        break
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
            finally:
                request.app.state.sse_clients[ip] = max(0, request.app.state.sse_clients[ip] - 1)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/runs/events", tags=["runs"], status_code=200)
    async def runs_events(
        request: Request, after: int = Query(default=0, ge=0, le=10000)
    ) -> StreamingResponse:
        require_auth(request)
        runner = get_runner(request)
        ip = _client_ip(request)
        if request.app.state.sse_clients[ip] >= MAX_SSE_PER_IP:
            raise HTTPException(status_code=429, detail={"error": "too many streams"})
        request.app.state.sse_clients[ip] += 1

        async def event_stream() -> AsyncIterator[str]:
            last = after
            loop = asyncio.get_running_loop()
            started = loop.time()
            last_ping = started
            yield ": connected\n\n"
            try:
                while True:
                    if loop.time() - started > SSE_MAX_SECONDS:
                        break
                    try:
                        disconnected = await asyncio.wait_for(
                            request.is_disconnected(), timeout=0.05
                        )
                    except TimeoutError:
                        disconnected = False
                    if disconnected:
                        break
                    for item in runner.events_after(last):
                        payload = json.dumps({"n": item.n, "event": item.event})
                        yield f"data: {payload}\n\n"
                        last = item.n
                    now = asyncio.get_running_loop().time()
                    if now - last_ping >= LOG_PING_SECONDS:
                        yield ": ping\n\n"
                        last_ping = now
                    await asyncio.sleep(LOG_POLL_SECONDS)
            except asyncio.CancelledError:
                return
            finally:
                request.app.state.sse_clients[ip] = max(0, request.app.state.sse_clients[ip] - 1)

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
    raw = str(os.environ.get("TRUSTED_PROXY_IPS") or "").strip()
    forwarded = [item.strip() for item in raw.split(",") if item.strip()] if raw else None
    uvicorn.run(
        app,
        host=host,
        port=port,
        workers=1,
        proxy_headers=proxy_headers or bool(forwarded),
        forwarded_allow_ips=forwarded if forwarded else None,
    )
