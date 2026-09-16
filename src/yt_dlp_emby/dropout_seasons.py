"""Discover Dropout catalog seasons from show pages."""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

_SEASON_IN_PATH = re.compile(r"/season:(\d+)(?:/|$)")
_SEASON_HREF = re.compile(r"/season:(\d+)")


def normalize_dropout_catalog_url(url: str) -> tuple[str, int | None]:
    """Return catalog base and optional season number if URL is a season page."""
    text = url.strip().rstrip("/")
    match = _SEASON_IN_PATH.search(text)
    if match:
        base = text[: match.start()].rstrip("/")
        return base, int(match.group(1))
    return text, None


def season_numbers_from_html(html: str, base_url: str) -> list[int]:
    found: set[int] = set()
    for match in _SEASON_HREF.finditer(html):
        found.add(int(match.group(1)))
    return sorted(found)


def probe_season_urls(
    catalog: str,
    *,
    fetch_html,
    max_season: int = 40,
    max_misses: int = 2,
) -> list[int]:
    """Probe season:N pages when the show page lists no seasons."""
    found: list[int] = []
    misses = 0
    for number in range(1, max_season + 1):
        url = f"{catalog.rstrip('/')}/season:{number}"
        try:
            html = fetch_html(url)
        except OSError:
            misses += 1
        else:
            if html and len(html) > 200:
                found.append(number)
                misses = 0
                continue
            misses += 1
        if misses >= max_misses and found:
            break
    return found


def discover_dropout_seasons(
    url: str,
    *,
    fetch_html,
) -> list[dict[str, object]]:
    catalog, lone = normalize_dropout_catalog_url(url)
    if lone is not None:
        return [
            {
                "dropout": lone,
                "url": f"{catalog}/season:{lone}",
                "to_season": lone,
                "enabled": True,
            }
        ]
    try:
        html = fetch_html(catalog)
    except OSError:
        numbers = probe_season_urls(catalog, fetch_html=fetch_html)
    else:
        numbers = season_numbers_from_html(html, catalog)
        if not numbers:
            numbers = probe_season_urls(catalog, fetch_html=fetch_html)
    return [
        {
            "dropout": n,
            "url": f"{catalog.rstrip('/')}/season:{n}",
            "to_season": n,
            "enabled": True,
        }
        for n in numbers
    ]
