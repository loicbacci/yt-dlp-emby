"""Write Emby/Kodi-compatible NFO files with YouTube IDs only."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from yt_dlp_emby.extract import EpisodeInfo

PLOT_LIMIT = 8000


def _set(parent: ET.Element, tag: str, text: str | int | None) -> None:
    child = ET.SubElement(parent, tag)
    if text is not None:
        child.text = str(text)


def _xml_bytes(root: ET.Element) -> bytes:
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + body + "\n").encode(
        "utf-8"
    )


def _write(path: Path, root: ET.Element) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_xml_bytes(root))


def _truncate(text: str) -> str:
    if len(text) <= PLOT_LIMIT:
        return text
    return text[: PLOT_LIMIT - 1].rstrip() + "…"


def _aired(upload_date: str | None) -> str | None:
    if not upload_date or len(upload_date) != 8 or not upload_date.isdigit():
        return None
    return f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"


def _runtime_minutes(duration: float | None) -> int | None:
    if duration is None:
        return None
    return max(1, int(round(duration / 60.0))) if duration >= 30 else 1 if duration > 0 else 0


def write_tvshow_nfo(
    path: Path,
    *,
    title: str,
    plot: str,
    channel_id: str,
    named_seasons: dict[int, str],
    premiered: str | None = None,
) -> None:
    root = ET.Element("tvshow")
    _set(root, "title", title)
    _set(root, "plot", _truncate(plot))
    _set(root, "studio", "YouTube")
    _set(root, "lockdata", "true")
    unique = ET.SubElement(root, "uniqueid", {"type": "youtube", "default": "true"})
    unique.text = channel_id
    if premiered:
        _set(root, "premiered", premiered)
    for number, name in sorted(named_seasons.items()):
        node = ET.SubElement(root, "namedseason", {"number": str(number)})
        node.text = name
    _write(path, root)


def write_season_nfo(path: Path, *, title: str, plot: str, season: int) -> None:
    root = ET.Element("season")
    _set(root, "title", title)
    _set(root, "plot", _truncate(plot))
    _set(root, "seasonnumber", season)
    _set(root, "lockdata", "true")
    _write(path, root)


def write_episode_nfo(
    path: Path,
    *,
    episode: EpisodeInfo,
    season: int,
    episode_number: int,
) -> None:
    root = ET.Element("episodedetails")
    _set(root, "title", episode.title)
    _set(root, "plot", _truncate(episode.description))
    _set(root, "season", season)
    _set(root, "episode", episode_number)
    aired = _aired(episode.upload_date)
    if aired:
        _set(root, "aired", aired)
    runtime = _runtime_minutes(episode.duration)
    if runtime:
        _set(root, "runtime", runtime)
    unique = ET.SubElement(root, "uniqueid", {"type": "youtube", "default": "true"})
    unique.text = episode.video_id
    _set(root, "lockdata", "true")
    if episode.webpage_url:
        _set(root, "showurl", episode.webpage_url)
    _write(path, root)
