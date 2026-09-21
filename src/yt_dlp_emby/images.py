"""Download artwork and convert it to JPEG for Emby."""

from __future__ import annotations

import ipaddress
import os
import socket
import tempfile
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

USER_AGENT = "yt-dlp-emby/0.1"
MAX_IMAGE_BYTES = 20 * 1024 * 1024
SOCKET_TIMEOUT = 15
_BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
_image_failures: dict[str, int] = {}


def jpeg_bytes_from_image(data: bytes) -> bytes:
    stripped = data.lstrip()
    if stripped.startswith(b"<svg") or stripped.startswith(b"<?xml"):
        raise ValueError("svg artwork is not supported")
    with Image.open(BytesIO(data)) as image:
        rgb = image.convert("RGB")
        out = BytesIO()
        rgb.save(out, format="JPEG", quality=90)
        return out.getvalue()


def write_image_from_bytes(data: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = jpeg_bytes_from_image(data)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".tmp", dir=dest.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, dest)
        # 0644: library artwork must be readable by the Emby UID (mkstemp tmp is 0600).
        os.chmod(dest, 0o644)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def save_jpeg(source: Path, dest: Path) -> None:
    write_image_from_bytes(source.read_bytes(), dest)


def note_image_failure(series_key: str, detail: str) -> None:
    """Warn once per series; keep a running failure count."""
    count = _image_failures.get(series_key, 0) + 1
    _image_failures[series_key] = count
    if count > 1:
        return
    from yt_dlp_emby.log import warn

    warn(f"could not download artwork for {series_key}: {detail}")


def reset_image_failures() -> None:
    _image_failures.clear()


def image_failure_count(series_key: str) -> int:
    return _image_failures.get(series_key, 0)


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def image_url_allowed(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.hostname
    if not host or host.lower() in _BLOCKED_HOSTS:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        raw = info[4][0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if _ip_is_blocked(ip):
            return False
    return True


class _PublicRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        if not image_url_allowed(str(newurl)):
            raise urllib.error.HTTPError(newurl, 403, "blocked redirect", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def artwork_exists(dest: Path) -> bool:
    try:
        return dest.is_file() and dest.stat().st_size > 0
    except OSError:
        return False


def download_image(
    url: str,
    dest: Path,
    timeout: float = SOCKET_TIMEOUT,
    *,
    series_key: str | None = None,
) -> bool:
    if artwork_exists(dest):
        return True
    if not image_url_allowed(url):
        if series_key:
            note_image_failure(series_key, url)
        return False
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_PublicRedirectHandler)
    try:
        with opener.open(request, timeout=timeout) as response:
            if not image_url_allowed(str(response.geturl())):
                if series_key:
                    note_image_failure(series_key, url)
                return False
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_IMAGE_BYTES:
                    if series_key:
                        note_image_failure(series_key, url)
                    return False
                chunks.append(chunk)
            data = b"".join(chunks)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        if series_key:
            note_image_failure(series_key, url)
        return False
    try:
        write_image_from_bytes(data, dest)
    except (OSError, ValueError, UnidentifiedImageError):
        if series_key:
            note_image_failure(series_key, url)
        return False
    return dest.is_file()
