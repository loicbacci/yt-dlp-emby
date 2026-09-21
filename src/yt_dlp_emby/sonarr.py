"""Fetch Sonarr series/episode lists by TVDB id."""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from yt_dlp_emby.cache import DROPOUT_CACHE_DIRNAME, atomic_write_text, file_lock, load_json_object
from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.images import MAX_IMAGE_BYTES, image_url_allowed

SONARR_CACHE_FILENAME = "sonarr.json"
TIMEOUT_SECONDS = 30
POSTER_TIMEOUT_SECONDS = 10

GetJson = Callable[[str, dict[str, str]], Any]


@dataclass(frozen=True)
class SonarrEpisode:
    season: int
    episode: int
    title: str
    air_date: str | None = None


_PLACEHOLDER_TITLES = frozenset({"tba", "tbd", "tbc"})


def sonarr_episode_is_out(
    title: str,
    air_date: str | None,
    *,
    today: date | None = None,
) -> bool:
    """False for TBA placeholders and episodes that have not aired yet."""
    label = title.strip().casefold()
    if not label or label in _PLACEHOLDER_TITLES:
        return False
    if not air_date or not str(air_date).strip():
        return True
    try:
        aired = date.fromisoformat(str(air_date).strip()[:10])
    except ValueError:
        return True
    return aired <= (today or datetime.now(timezone.utc).date())


def sonarr_cache_path(manifest_path: Path | None = None, *, cwd: Path | None = None) -> Path:
    root = manifest_path.parent if manifest_path is not None else (cwd or Path.cwd())
    return root / DROPOUT_CACHE_DIRNAME / SONARR_CACHE_FILENAME


def load_sonarr_cache(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    data = load_json_object(path, kind="sonarr cache")
    result: dict[str, dict] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[str(key)] = value
    return result


def save_sonarr_cache(path: Path, payload: dict[str, dict]) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _default_get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise exc
    except OSError as exc:
        raise ConfigError(f"Sonarr request failed: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError("Sonarr returned invalid JSON") from exc


def _parse_air_date(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def _raise_http(exc: urllib.error.HTTPError) -> None:
    if exc.code in (401, 403):
        raise ConfigError("Sonarr API key rejected") from exc
    raise ConfigError(f"Sonarr request failed: HTTP {exc.code}") from exc


def _sonarr_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Reject metadata/link-local SSRF targets. RFC1918 and loopback are OK."""
    return bool(ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def assert_sonarr_url_allowed(url: str, *, environ: Mapping[str, str] | None = None) -> None:
    """Allow LAN/loopback Sonarr (typical homelab). Still reject link-local/metadata.

    ``ALLOW_PRIVATE_SONARR`` is kept as a no-op compatibility flag: private
    RFC1918/loopback hosts are always allowed for this configured service URL.
    """
    _ = environ
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError("Sonarr URL must be http(s) with a hostname")
    host = parsed.hostname
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and _sonarr_ip_blocked(literal):
        raise ConfigError("URL points to a private or reserved address")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return
    for info in infos:
        raw = info[4][0]
        try:
            resolved = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if _sonarr_ip_blocked(resolved):
            raise ConfigError("URL resolves to a private or reserved address")


def ping_sonarr(
    *,
    base_url: str,
    api_key: str,
    get_json: GetJson | None = None,
) -> dict[str, Any]:
    if get_json is None:
        assert_sonarr_url_allowed(base_url)
    get = get_json or _default_get_json
    base = base_url.rstrip("/")
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    try:
        data = get(f"{base}/api/v3/system/status", headers)
    except urllib.error.HTTPError as exc:
        _raise_http(exc)
    if not isinstance(data, dict):
        raise ConfigError("Sonarr status was not an object")
    version = str(data.get("version") or "").strip() or None
    instance = str(data.get("instanceName") or data.get("appName") or "").strip() or None
    return {"ok": True, "version": version, "instance": instance}


def fetch_episodes(
    tvdb_id: int,
    *,
    base_url: str,
    api_key: str,
    get_json: GetJson | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, list[SonarrEpisode]]:
    if get_json is None:
        assert_sonarr_url_allowed(base_url)
    get = get_json or _default_get_json
    base = base_url.rstrip("/")
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    try:
        series_list = get(f"{base}/api/v3/series?tvdbId={tvdb_id}", headers)
    except urllib.error.HTTPError as exc:
        _raise_http(exc)
    if not isinstance(series_list, list) or not series_list:
        raise ConfigError(f"Sonarr has no series with tvdb_id={tvdb_id}")
    first = series_list[0]
    if not isinstance(first, dict) or first.get("id") is None:
        raise ConfigError(f"Sonarr has no series with tvdb_id={tvdb_id}")
    series_id = first["id"]
    title = str(first.get("title") or "").strip() or f"tvdb_id={tvdb_id}"
    if extra is not None:
        extra["title_slug"] = str(first.get("titleSlug") or "").strip() or None
        extra["id"] = series_id
    try:
        raw_episodes = get(f"{base}/api/v3/episode?seriesId={series_id}", headers)
    except urllib.error.HTTPError as exc:
        _raise_http(exc)
    if not isinstance(raw_episodes, list):
        raise ConfigError("Sonarr episode list was not an array")
    episodes: list[SonarrEpisode] = []
    for item in raw_episodes:
        if not isinstance(item, dict):
            continue
        number = item.get("episodeNumber")
        season = item.get("seasonNumber")
        if number is None or season is None:
            continue
        if isinstance(number, bool) or isinstance(season, bool):
            continue
        if not isinstance(number, int) or not isinstance(season, int):
            continue
        episodes.append(
            SonarrEpisode(
                season=season,
                episode=number,
                title=str(item.get("title") or "").strip(),
                air_date=_parse_air_date(item.get("airDate") or item.get("airDateUtc")),
            )
        )
    return title, episodes


def _episodes_from_cache(raw: dict) -> tuple[str, list[SonarrEpisode], str | None]:
    title = str(raw.get("title") or "")
    title_slug = str(raw.get("title_slug") or "").strip() or None
    items = raw.get("episodes") or []
    episodes: list[SonarrEpisode] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            season = item.get("season")
            episode = item.get("episode")
            if not isinstance(season, int) or not isinstance(episode, int):
                continue
            episodes.append(
                SonarrEpisode(
                    season=season,
                    episode=episode,
                    title=str(item.get("title") or ""),
                    air_date=_parse_air_date(item.get("air_date")),
                )
            )
    return title, episodes, title_slug


def _looks_like_image(data: bytes, content_type: str | None) -> bool:
    stripped = data.lstrip()[:64].lower()
    if stripped.startswith(b"<svg") or stripped.startswith(b"<?xml"):
        return False
    if data[:2] == b"\xff\xd8":
        return True
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    ctype = (content_type or "").split(";")[0].strip().lower()
    if "svg" in ctype:
        return False
    return ctype.startswith("image/") and "html" not in ctype


# Accepted risk (DNS rebinding TOCTOU): poster/direct image fetches resolve the
# host once in image_url_allowed, but urllib may resolve it again when opening
# the connection, so a rebinding attacker could theoretically redirect a fetch
# to a private IP. IP pinning is infeasible with plain urllib here; mitigations
# in place are single-resolution guards on the initial URL, on every redirect
# hop (_PosterRedirectHandler), and on the final response URL below.
class _PosterRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not image_url_allowed(str(newurl)):
            raise urllib.error.HTTPError(newurl, 403, "blocked redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_url_bytes(url: str, headers: dict[str, str]) -> tuple[bytes, str | None]:
    if not image_url_allowed(url):
        raise ConfigError("blocked image URL")
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_PosterRedirectHandler)
    with opener.open(request, timeout=POSTER_TIMEOUT_SECONDS) as response:
        if not image_url_allowed(str(response.geturl())):
            raise ConfigError("blocked image URL")
        content_type = response.headers.get("Content-Type")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise ConfigError("image too large")
            chunks.append(chunk)
        return b"".join(chunks), content_type


def _fetch_sonarr_local_bytes(url: str, headers: dict[str, str]) -> tuple[bytes, str | None]:
    """Fetch MediaCover from the configured Sonarr host, including LAN IPs."""
    try:
        assert_sonarr_url_allowed(url)
    except ConfigError as exc:
        raise ConfigError("blocked image URL") from exc
    request = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener(_SonarrLocalRedirectHandler)
    with opener.open(request, timeout=POSTER_TIMEOUT_SECONDS) as response:
        try:
            assert_sonarr_url_allowed(str(response.geturl()))
        except ConfigError as exc:
            raise ConfigError("blocked image URL") from exc
        content_type = response.headers.get("Content-Type")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise ConfigError("image too large")
            chunks.append(chunk)
        return b"".join(chunks), content_type


class _SonarrLocalRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        try:
            assert_sonarr_url_allowed(str(newurl))
        except ConfigError as exc:
            raise urllib.error.HTTPError(newurl, 403, "blocked redirect", headers, fp) from exc
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_sonarr_poster(
    tvdb_id: int,
    *,
    base_url: str,
    api_key: str,
    get_json: GetJson | None = None,
    get_bytes: Callable[[str, dict[str, str]], tuple[bytes, str | None]] | None = None,
) -> bytes | None:
    get = get_json or _default_get_json
    fetch = get_bytes or _fetch_url_bytes
    if get_json is None:
        try:
            assert_sonarr_url_allowed(base_url)
        except ConfigError:
            return None
    base = base_url.rstrip("/")
    sonarr_host = (urlparse(base).hostname or "").lower()

    def fetch_poster(url: str, headers: dict[str, str]) -> tuple[bytes, str | None]:
        if get_bytes is not None:
            return fetch(url, headers)
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host and host == sonarr_host:
            return _fetch_sonarr_local_bytes(url, headers)
        return fetch(url, headers)

    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    try:
        series_list = get(f"{base}/api/v3/series?tvdbId={tvdb_id}", headers)
    except (urllib.error.HTTPError, ConfigError):
        return None
    if not isinstance(series_list, list) or not series_list:
        return None
    first = series_list[0]
    if not isinstance(first, dict) or first.get("id") is None:
        return None
    series_id = first["id"]
    urls: list[str] = []
    for image in first.get("images") or []:
        if not isinstance(image, dict):
            continue
        if str(image.get("coverType") or "").lower() != "poster":
            continue
        remote = str(image.get("remoteUrl") or "").strip()
        local = str(image.get("url") or "").strip()
        if remote.startswith(("http://", "https://")):
            urls.append(remote)
        if local.startswith(("http://", "https://")):
            urls.append(local.split("?", 1)[0])
        elif local.startswith("/"):
            urls.append(f"{base}{local.split('?', 1)[0]}")
    urls.append(f"{base}/api/v3/mediacover/{series_id}/poster.jpg")
    urls.append(f"{base}/MediaCover/{series_id}/poster.jpg")
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            data, content_type = fetch_poster(url, headers)
        except (urllib.error.HTTPError, OSError, ConfigError):
            continue
        if data and _looks_like_image(data, content_type):
            try:
                from yt_dlp_emby.images import jpeg_bytes_from_image

                return jpeg_bytes_from_image(data)
            except (OSError, ValueError):
                if data[:2] == b"\xff\xd8":
                    return data
                continue
    return None


def fetch_episodes_cached(
    tvdb_id: int,
    *,
    base_url: str,
    api_key: str,
    cache_path: Path,
    force_refetch: bool = False,
    get_json: GetJson | None = None,
) -> tuple[str, list[SonarrEpisode]]:
    title, episodes, _slug = fetch_episodes_cached_meta(
        tvdb_id,
        base_url=base_url,
        api_key=api_key,
        cache_path=cache_path,
        force_refetch=force_refetch,
        get_json=get_json,
    )
    return title, episodes


def fetch_episodes_cached_meta(
    tvdb_id: int,
    *,
    base_url: str,
    api_key: str,
    cache_path: Path,
    force_refetch: bool = False,
    get_json: GetJson | None = None,
) -> tuple[str, list[SonarrEpisode], str | None]:
    key = str(tvdb_id)
    with file_lock(cache_path):
        if not force_refetch:
            cached = load_sonarr_cache(cache_path).get(key)
            if cached is not None:
                return _episodes_from_cache(cached)
        extra: dict[str, Any] = {}
        title, episodes = fetch_episodes(
            tvdb_id,
            base_url=base_url,
            api_key=api_key,
            get_json=get_json,
            extra=extra,
        )
        title_slug = extra.get("title_slug") if isinstance(extra.get("title_slug"), str) else None
        cache = load_sonarr_cache(cache_path)
        cache[key] = {
            "title": title,
            "title_slug": title_slug,
            "episodes": [
                {
                    "season": item.season,
                    "episode": item.episode,
                    "title": item.title,
                    "air_date": item.air_date,
                }
                for item in episodes
            ],
        }
        save_sonarr_cache(cache_path, cache)
        return title, episodes, title_slug
