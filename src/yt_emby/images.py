"""Download artwork and convert it to JPEG for Emby."""

from __future__ import annotations

import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

USER_AGENT = "yt-emby/0.1 (+https://github.com/)"


def write_image_from_bytes(data: bytes, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(data)) as image:
        rgb = image.convert("RGB")
        rgb.save(dest, format="JPEG", quality=90)


def save_jpeg(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        rgb = image.convert("RGB")
        rgb.save(dest, format="JPEG", quality=90)


def download_image(url: str, dest: Path, timeout: float = 30.0) -> bool:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return False
    try:
        write_image_from_bytes(data, dest)
    except OSError:
        return False
    return dest.is_file()
