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
from typing import Any, AsyncIterator, Callable, Mapping, Sequence
from urllib.parse import urlparse

import itsdangerous
import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from itsdangerous.exc import BadSignature
from pydantic import BaseModel, ConfigDict, Field
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
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
from yt_dlp_emby.server import views as cached_views
from yt_dlp_emby.server.auth import (
    AuthState,
    change_password,
    load_auth,
    setup_password,
    verify_password,
)
from yt_dlp_emby.server.job_models import JobList, JobSnapshot, job_request_adapter
from yt_dlp_emby.server.job_store import JobStore, utc_now
from yt_dlp_emby.server.jobs import JobConflict, JobCoordinator
from yt_dlp_emby.server.manifests import (
    ALLOWED,
    paths_from_text,
    read_manifest,
    validate_manifest_text,
    write_import,
    write_manifest,
)
from yt_dlp_emby.server.series import (
    AmbiguousSlugError,
    SeriesExistsError,
    add_series_source,
    create_series,
    delete_series,
    delete_series_source,
    get_series_yaml,
    patch_platform_cookies_field,
    platform_payload,
    put_platform,
    put_series,
    put_series_yaml,
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


class ImportManifestBody(BaseModel):
    path: str = Field(min_length=1, max_length=512)
    text: str = Field(max_length=2_000_000)


class CookieBody(BaseModel):
    text: str = Field(max_length=2_000_000)


class ConfigBody(BaseModel):
    library: str | None = Field(default=None, max_length=4096)
    old_dir: str | None = Field(default=None, max_length=4096)
    staging: str | None = Field(default=None, max_length=4096)
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
    worker_command_factory: Callable[[dict[str, Any]], Sequence[str]] | None = None,
) -> FastAPI:
    if environ is None:
        environ = os.environ
    resolved_data = resolve_data_dir(data_dir, environ)
    resolved_data.mkdir(parents=True, exist_ok=True)
    static_root = _static_dir(environ)
    initial_auth = load_auth(resolved_data, environ)

    store = JobStore(resolved_data / "jobs.sqlite3")
    coordinator = JobCoordinator(resolved_data, environ, store, worker_command_factory)
    coordinator_lock: Any = None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal coordinator_lock
        import fcntl

        coordinator_lock = (resolved_data / "coordinator.lock").open("a+")
        try:
            fcntl.flock(coordinator_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            coordinator_lock.close()
            raise RuntimeError("another server owns this data directory") from exc
        try:
            from yt_dlp_emby.server.migration import archive_legacy_state

            await asyncio.to_thread(archive_legacy_state, resolved_data)
            await coordinator.recover()
        except Exception:
            fcntl.flock(coordinator_lock.fileno(), fcntl.LOCK_UN)
            coordinator_lock.close()
            raise
        try:
            yield
        finally:
            await coordinator.shutdown()
            store.close()
            fcntl.flock(coordinator_lock.fileno(), fcntl.LOCK_UN)
            coordinator_lock.close()

    app = FastAPI(lifespan=lifespan)
    app.state.data_dir = resolved_data
    app.state.environ = environ
    app.state.auth = initial_auth
    app.state.job_store = store
    app.state.job_coordinator = coordinator
    app.state.manifest_lock = asyncio.Lock()
    app.state.login_hits = defaultdict(deque)

    def _error_body(detail: Any) -> dict[str, Any]:
        if isinstance(detail, dict):
            if "error" in detail:
                body = dict(detail)
            else:
                body = {"error": detail}
        else:
            body = {"error": str(detail)}
        body.setdefault("code", "HTTP_ERROR")
        body.setdefault("request_id", secrets.token_hex(8))
        return body

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if not isinstance(exc, StarletteHTTPException):
            return JSONResponse(status_code=500, content=_error_body("internal error"))
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
            status_code=400,
            content={
                "error": "validation error",
                "code": "INVALID_REQUEST",
                "request_id": secrets.token_hex(8),
                "fields": fields,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, HTTPException):
            return JSONResponse(status_code=exc.status_code, content=_error_body(exc.detail))
        return JSONResponse(status_code=500, content={"error": "internal error"})

    def get_auth(request: Request) -> AuthState:
        return request.app.state.auth

    @asynccontextmanager
    async def manifest_maintenance(request: Request) -> AsyncIterator[None]:
        """Serialize canonical edits against active jobs."""
        async with request.app.state.manifest_lock:
            active, _, _ = request.app.state.job_store.list_jobs(limit=1)
            if active:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "a job is in progress",
                        "code": "JOB_CONFLICT",
                        "job_id": active["id"],
                    },
                )
            try:
                yield
            finally:
                pass

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
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "manifest changed", "code": "CONFIG_CHANGED"},
                    )
            try:
                payload = await asyncio.to_thread(
                    write_manifest, request.app.state.data_dir, kind, body.text
                )
            except ConfigError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
            store.invalidate_platform(kind)
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
            store.invalidate_platform(kind)
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
            store.invalidate_platform(kind)
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
            "shows_dir": (body.shows_dir or "").strip() or None,
            "sonarr_url": (body.sonarr_url or "").strip() or None,
            "sonarr_api_key": (body.sonarr_api_key or "").strip() or None,
        }
        data_dir = request.app.state.data_dir
        environ = request.app.state.environ
        _assert_safe_fs_path(values["library"], "library", data_dir=data_dir, environ=environ)
        _assert_safe_fs_path(values["old_dir"], "old_dir", data_dir=data_dir, environ=environ)
        _assert_safe_fs_path(values["staging"], "staging", data_dir=data_dir, environ=environ)
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
            async with manifest_maintenance(request):
                await asyncio.to_thread(write_config, path, values)
                store.invalidate_all()
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
            async with manifest_maintenance(request):
                written = await asyncio.to_thread(
                    write_cookie_jar,
                    request.app.state.data_dir,
                    kind,
                    body.text,
                    filename=str(field) if field else None,
                )
                store.invalidate_platform(kind)
            if (
                confined_cookie_path(request.app.state.data_dir, str(field) if field else None)
                is None
            ):
                if root.is_file():
                    async with manifest_maintenance(request):
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
        async with manifest_maintenance(request):
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
                store.invalidate_platform(kind)
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
            cached_views.series_list,
            request.app.state.data_dir,
            request.app.state.environ,
            store,
        )

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
        "/api/series/{platform}/{slug}",
        tags=["series"],
        status_code=200,
        response_model=dict[str, Any],
    )
    async def get_series_detail(platform: str, slug: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            return await asyncio.to_thread(
                cached_views.series_detail,
                request.app.state.data_dir,
                request.app.state.environ,
                store,
                platform,
                slug,
            )
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
                result = await asyncio.to_thread(
                    put_series_yaml,
                    request.app.state.data_dir,
                    platform,
                    slug,
                    body.text,
                    environ=request.app.state.environ,
                )
                await asyncio.to_thread(
                    cached_views.replan_cached,
                    request.app.state.data_dir,
                    request.app.state.environ,
                    store,
                    platform,
                    slug,
                )
                return result
            except KeyError:
                raise HTTPException(status_code=404, detail={"error": "not found"})
            except SeriesExistsError as exc:
                raise HTTPException(status_code=409, detail={"error": str(exc)}) from exc
            except (ConfigError, ValueError) as exc:
                raise HTTPException(
                    status_code=_series_value_status(exc), detail={"error": str(exc)}
                ) from exc

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
                result = await asyncio.to_thread(
                    put_series,
                    request.app.state.data_dir,
                    platform,
                    slug,
                    payload,
                    environ=request.app.state.environ,
                )
                await asyncio.to_thread(
                    cached_views.replan_cached,
                    request.app.state.data_dir,
                    request.app.state.environ,
                    store,
                    platform,
                    slug,
                )
                return result
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
                store.delete_view(platform, slug)
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
                result = await asyncio.to_thread(
                    add_series_source,
                    request.app.state.data_dir,
                    platform,
                    slug,
                    body.url,
                    environ=request.app.state.environ,
                )
                await asyncio.to_thread(
                    cached_views.replan_cached,
                    request.app.state.data_dir,
                    request.app.state.environ,
                    store,
                    platform,
                    slug,
                )
                return result
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
                result = await asyncio.to_thread(
                    delete_series_source,
                    request.app.state.data_dir,
                    platform,
                    slug,
                    source_id,
                    environ=request.app.state.environ,
                )
                await asyncio.to_thread(
                    cached_views.replan_cached,
                    request.app.state.data_dir,
                    request.app.state.environ,
                    store,
                    platform,
                    slug,
                )
                return result
            except KeyError:
                raise HTTPException(status_code=404, detail={"error": "not found"})
            except ValueError as exc:
                raise HTTPException(
                    status_code=_series_value_status(exc), detail={"error": str(exc)}
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
                cached_views.disk_view,
                request.app.state.data_dir,
                request.app.state.environ,
                store,
                platform,
                slug,
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
                cached_views.missing_view,
                request.app.state.data_dir,
                request.app.state.environ,
                store,
                platform,
                slug,
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
                cached_views.episodes_view,
                request.app.state.data_dir,
                request.app.state.environ,
                store,
                platform,
                slug,
                source_id,
                season_id,
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

    def job_snapshot(
        job_id: str, log_after: int = 0, *, include_logs: bool = True
    ) -> dict[str, Any]:
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail={"error": "not found", "code": "NOT_FOUND"})
        logs, cursor, truncated = (
            store.logs_after(job_id, log_after) if include_logs else ([], 0, False)
        )
        return {
            "id": job["id"],
            "kind": job["kind"],
            "status": job["status"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "finished_at": job["finished_at"],
            "progress": job["progress"],
            "result": job["result"],
            "error": job["error"],
            "logs": logs,
            "log_cursor": cursor,
            "logs_truncated": truncated,
            "can_cancel": job["status"] in {"queued", "running", "stopping"},
            "can_retry": job["status"] in {"failed", "cancelled", "interrupted"},
        }

    @app.post("/api/jobs", tags=["jobs"], status_code=202)
    async def post_job(request: Request) -> JSONResponse:
        require_auth(request)
        from pydantic import ValidationError

        try:
            payload = job_request_adapter.validate_python(await request.json())
        except (ValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail={"error": "validation error", "code": "INVALID_REQUEST"}
            ) from exc
        async with request.app.state.manifest_lock:
            if payload.kind == "refresh" and payload.expected_revision:
                from yt_dlp_emby.server.services import current_configuration_revision

                for target in payload.items:
                    try:
                        actual_revision = await asyncio.to_thread(
                            current_configuration_revision,
                            request.app.state.data_dir,
                            request.app.state.environ,
                            target.platform,
                            target.slug,
                        )
                    except (KeyError, ValueError) as exc:
                        raise HTTPException(
                            status_code=409,
                            detail={"error": "configuration changed", "code": "CONFIG_CHANGED"},
                        ) from exc
                    if actual_revision != payload.expected_revision:
                        raise HTTPException(
                            status_code=409,
                            detail={"error": "configuration changed", "code": "CONFIG_CHANGED"},
                        )
            payload_data = payload.model_dump(exclude_none=True)
            if payload.kind == "download":
                current = await asyncio.to_thread(
                    cached_views.latest_plan,
                    request.app.state.data_dir,
                    request.app.state.environ,
                    store,
                    force=payload.force,
                    create=payload.create,
                )
                if current is None:
                    raise HTTPException(
                        status_code=409, detail={"error": "no current plan", "code": "PLAN_STALE"}
                    )
                if current.get("readiness") != "ready":
                    code = (
                        "LIBRARY_UNAVAILABLE"
                        if current.get("readiness") == "unavailable"
                        else "PLAN_STALE"
                    )
                    raise HTTPException(
                        status_code=409, detail={"error": "plan is not ready", "code": code}
                    )
                if payload.plan_id != current.get("plan_id"):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "plan changed; refresh before downloading",
                            "code": "PLAN_STALE",
                        },
                    )
                try:
                    selection = await asyncio.to_thread(
                        cached_views.executable_selection,
                        request.app.state.data_dir,
                        request.app.state.environ,
                        store,
                        payload.plan_id,
                        payload.ids,
                        force=payload.force,
                        create=payload.create,
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "selection no longer belongs to this plan",
                            "code": "PLAN_STALE",
                        },
                    ) from exc
                payload_data["selected_actions"] = selection["selected_actions"]
                payload_data["cached_views"] = selection["cached_views"]
            try:
                job_id = await coordinator.start(payload_data)
            except JobConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail={"error": str(exc), "code": "JOB_CONFLICT", "job_id": exc.job_id},
                ) from exc
        return JSONResponse({"job_id": job_id, "status": "queued"}, status_code=202)

    @app.get("/api/jobs", tags=["jobs"], response_model=JobList)
    async def get_jobs(
        request: Request, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)
    ) -> dict[str, Any]:
        require_auth(request)
        active, history, total = store.list_jobs(offset, limit)
        return {
            "active": job_snapshot(active["id"], 0, include_logs=False) if active else None,
            "history": [job_snapshot(x["id"], 0, include_logs=False) for x in history],
            "total": total,
        }

    @app.get("/api/jobs/{job_id}", tags=["jobs"], response_model=JobSnapshot)
    async def get_job(
        job_id: str, request: Request, log_after: int = Query(0, ge=0)
    ) -> dict[str, Any]:
        require_auth(request)
        return job_snapshot(job_id, log_after)

    @app.post("/api/jobs/{job_id}/cancel", tags=["jobs"], response_model=JobSnapshot)
    async def cancel_job(job_id: str, request: Request) -> dict[str, Any]:
        require_auth(request)
        try:
            await coordinator.cancel(job_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404, detail={"error": "not found", "code": "NOT_FOUND"}
            ) from exc
        return job_snapshot(job_id)

    @app.post("/api/jobs/{job_id}/retry", tags=["jobs"], status_code=202)
    async def retry_job(job_id: str, request: Request) -> JSONResponse:
        require_auth(request)
        old = store.get(job_id)
        if old is None:
            raise HTTPException(status_code=404, detail={"error": "not found", "code": "NOT_FOUND"})
        if old["status"] not in {"failed", "cancelled", "interrupted"}:
            raise HTTPException(
                status_code=409, detail={"error": "job cannot be retried", "code": "JOB_CONFLICT"}
            )
        retry_request = dict(old["request"])
        completed = store.completed_items(job_id)
        if retry_request.get("kind") == "refresh":
            completed_targets = {
                (row["identity"].get("platform"), row["identity"].get("slug"))
                for row in completed
                if isinstance(row.get("identity"), dict)
            }
            retry_request["items"] = [
                target
                for target in retry_request.get("items", [])
                if (target.get("platform"), target.get("slug")) not in completed_targets
            ]
        elif retry_request.get("kind") == "download":
            completed_ids = {
                identity["id"]
                for row in completed
                if isinstance((identity := row.get("identity")), dict)
                and isinstance(identity.get("id"), str)
            }
            old_rows = {
                str(row.get("id")): row
                for row in retry_request.get("selected_actions", [])
                if isinstance(row, dict) and isinstance(row.get("id"), str)
            }
            old_cached_views = retry_request.get("cached_views", [])
            if not old_rows or not old_cached_views:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "original selection snapshots are unavailable",
                        "code": "PLAN_STALE",
                    },
                )
            try:
                from yt_dlp_emby.server.services import (
                    refresh_cached_disk_views,
                    verify_completed_actions,
                )

                verified_ids = await asyncio.to_thread(
                    verify_completed_actions,
                    request.app.state.data_dir,
                    request.app.state.environ,
                    list(old_rows.values()),
                    old_cached_views,
                )
                refreshed_views = await asyncio.to_thread(
                    refresh_cached_disk_views,
                    request.app.state.data_dir,
                    request.app.state.environ,
                    old_cached_views,
                    force=bool(retry_request.get("force")),
                    create=bool(retry_request.get("create")),
                )
            except (OSError, ValueError, RuntimeError) as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "selected targets changed; refresh and replan",
                        "code": "PLAN_STALE",
                    },
                ) from exc
            stamp = utc_now()
            for target_view in refreshed_views:
                view = target_view["view"]
                plan = target_view["plan"]
                view["plan_id"] = plan["plan_id"]
                store.put_view(
                    target_view["platform"],
                    target_view["slug"],
                    {"view": view},
                    plan,
                    str(plan.get("revision", "")),
                    "ready",
                    stamp,
                    stamp,
                )
            current = await asyncio.to_thread(
                cached_views.latest_plan,
                request.app.state.data_dir,
                request.app.state.environ,
                store,
                force=bool(retry_request.get("force")),
                create=bool(retry_request.get("create")),
            )
            if current is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "no current cached plan is available for retry",
                        "code": "PLAN_STALE",
                    },
                )
            current_rows = [
                row
                for source in (current.get("sources") or {}).values()
                for row in source.get("items", [])
                if isinstance(row, dict)
            ]
            current_by_semantic = {
                (
                    str(row.get("execution_id") or ""),
                    str(row.get("provider_identity") or row.get("source_id") or ""),
                ): row
                for row in current_rows
            }
            remaining_current_ids: list[str] = []
            for old_id in retry_request.get("ids", []):
                old_row = old_rows.get(old_id)
                if old_row is None:
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "original selection is unavailable", "code": "PLAN_STALE"},
                    )
                semantic_key = (
                    str(old_row.get("execution_id") or ""),
                    str(old_row.get("provider_identity") or old_row.get("source_id") or ""),
                )
                current_row = current_by_semantic.get(semantic_key)
                if old_id in completed_ids and old_id in verified_ids:
                    continue
                if current_row is None or current_row.get("action") not in {
                    "download",
                    "replace",
                    "rename",
                    "remove",
                }:
                    raise HTTPException(
                        status_code=409,
                        detail={"error": "remaining selection changed", "code": "PLAN_STALE"},
                    )
                remaining_current_ids.append(str(current_row["id"]))
            retry_request["plan_id"] = current["plan_id"]
            retry_request["ids"] = remaining_current_ids
            if retry_request["ids"]:
                try:
                    selection = await asyncio.to_thread(
                        cached_views.executable_selection,
                        request.app.state.data_dir,
                        request.app.state.environ,
                        store,
                        retry_request["plan_id"],
                        retry_request["ids"],
                        force=bool(retry_request.get("force")),
                        create=bool(retry_request.get("create")),
                    )
                except ValueError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "error": "plan changed; build a fresh plan before retry",
                            "code": "PLAN_STALE",
                        },
                    ) from exc
                retry_request["selected_actions"] = selection["selected_actions"]
                retry_request["cached_views"] = selection["cached_views"]
        if not retry_request.get("items", retry_request.get("ids", [True])):
            raise HTTPException(
                status_code=409,
                detail={"error": "all selected items already completed", "code": "JOB_CONFLICT"},
            )
        async with request.app.state.manifest_lock:
            try:
                new_id = await coordinator.start(retry_request, retry_parent=job_id)
            except JobConflict as exc:
                raise HTTPException(
                    status_code=409,
                    detail={"error": str(exc), "code": "JOB_CONFLICT", "job_id": exc.job_id},
                ) from exc
        return JSONResponse({"job_id": new_id, "status": "queued"}, status_code=202)

    @app.get("/api/plans/latest", tags=["plans"])
    async def get_plans_latest(
        request: Request, force: bool = False, create: bool = False
    ) -> dict[str, Any]:
        require_auth(request)
        plan = await asyncio.to_thread(
            cached_views.latest_plan,
            request.app.state.data_dir,
            request.app.state.environ,
            store,
            force=force,
            create=create,
        )
        if plan is None:
            raise HTTPException(
                status_code=404, detail={"error": "no cached plan", "code": "NOT_FOUND"}
            )
        return plan

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
