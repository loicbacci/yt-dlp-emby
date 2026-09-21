#!/usr/bin/env python3
"""Build Cosmos mockup catalog from manifests + Sonarr.

Local-only. Statuses are fictional. Catalog data is not production truth.

  uv run python scripts/dev/build-mock-catalog.py --help
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(os.environ.get("YT_DLP_EMBY_ROOT", Path(__file__).resolve().parents[2]))
DATA = Path(os.environ.get("YT_DLP_EMBY_DATA", "/docker/yt-dlp-emby"))
SONARR_DB = Path(os.environ.get("SONARR_DB", "/docker/sonarr/sonarr.db"))
OUT_JSON = ROOT / "web/src/mockups/catalog.json"
POSTER_DIR = ROOT / "web/public/mockups"
TONES = ("terra", "teal", "rose", "gold", "blue")

# Catch-up inbox stress data — not on-disk truth. D20 later seasons stay missing.
MISSING_FROM_SEASON = {
    "dimension-20": 21,
    "dimension-20-adventuring-party": 21,
    "game-changer": 8,
    "crowd-control": 2,
    "make-some-noise": 4,
    "parlor-room": 2,
    "smartypants": 3,
    "um-actually": 11,
    "very-important-people": 3,
    "professor-messer": 2,
}


def sonarr_ids_by_tvdb() -> dict[int, int]:
    db = SONARR_DB
    if not db.is_file():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT Id, TvdbId FROM Series WHERE TvdbId IS NOT NULL")
            return {int(tvdb): int(sid) for sid, tvdb in rows if tvdb}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"sonarr db unreadable: {exc}", file=sys.stderr)
        return {}


def fetch_poster(tvdb_id: int, slug: str, ids: dict[int, int]) -> str | None:
    dest = POSTER_DIR / f"poster-{slug}.jpg"
    if dest.is_file() and dest.stat().st_size > 0:
        return f"/mockups/poster-{slug}.jpg"
    sid = ids.get(tvdb_id)
    if sid is None:
        return None
    src = Path(f"/docker/sonarr/MediaCover/{sid}/poster.jpg")
    if not src.is_file():
        return None
    dest.write_bytes(src.read_bytes())
    print(f"poster {slug} <- MediaCover/{sid}", file=sys.stderr)
    return f"/mockups/poster-{slug}.jpg"


def copy_library_poster(src: Path, slug: str) -> str | None:
    dest = POSTER_DIR / f"poster-{slug}.jpg"
    if dest.is_file() and dest.stat().st_size > 0:
        return f"/mockups/poster-{slug}.jpg"
    if not src.is_file():
        return None
    dest.write_bytes(src.read_bytes())
    return f"/mockups/poster-{slug}.jpg"


def letter_for(name: str) -> str:
    for ch in name:
        if ch.isalnum():
            return ch.upper()
    return "?"


def dest_meta(n: int, titles: list[str]) -> tuple[str, str]:
    unique = list(dict.fromkeys(t for t in titles if t))
    folder = "Specials" if n == 0 else f"Season {n}"
    if unique:
        return unique[0], folder
    return folder, folder


def fictional_status(slug: str, season: int, episode: int, skipped: bool) -> str:
    if skipped:
        return "skipped"
    floor = MISSING_FROM_SEASON.get(slug)
    if slug == "dimension-20" and season == 0 and episode >= 58:
        return "missing"
    if floor is not None and season >= floor:
        return "missing"
    return "library"


def load_sonarr() -> dict[str, dict]:
    path = DATA / "cache" / "sonarr.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def load_dropout_cache() -> dict[str, list]:
    path = DATA / "cache" / "dropout.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    seasons = raw.get("seasons") if isinstance(raw, dict) else None
    return seasons if isinstance(seasons, dict) else {}


def remap_payload(remap) -> dict:
    row: dict = {"dropoutEpisode": remap.dropout_episode}
    if remap.skip:
        row["skip"] = True
    if remap.to_season is not None:
        row["toSeason"] = remap.to_season
    if remap.to_episode is not None:
        row["toEpisode"] = remap.to_episode
    if remap.title:
        row["title"] = remap.title
    return row


def apply_remap(ep: dict, remap) -> dict:
    if remap.skip:
        ep["skip"] = True
    if remap.to_season is not None:
        ep["toSeason"] = remap.to_season
    if remap.to_episode is not None:
        ep["toEpisode"] = remap.to_episode
    if remap.title:
        ep["remapTitle"] = remap.title
    return ep


def map_season_row(source, season_obj, cache: dict[str, list]) -> dict:
    from yt_dlp_emby.dropout_manifest import season_page_url

    remaps = {r.dropout_episode: r for r in season_obj.remap}
    allowed = set(season_obj.only_episodes) if season_obj.only_episodes else None
    page = season_page_url(source, season_obj)
    listings = cache.get(page) or []
    episodes: list[dict] = []
    seen: set[int] = set()
    for item in listings:
        n = item.get("dropout_episode")
        if not isinstance(n, int):
            continue
        seen.add(n)
        ep = {"n": n, "title": str(item.get("title") or f"Episode {n}")}
        if allowed is not None and n not in allowed:
            ep["skip"] = True
        remap = remaps.get(n)
        if remap is not None:
            apply_remap(ep, remap)
        episodes.append(ep)
    for n, remap in sorted(remaps.items()):
        if n in seen:
            continue
        ep = {"n": n, "title": remap.title or f"Episode {n}"}
        if allowed is not None and n not in allowed:
            ep["skip"] = True
        apply_remap(ep, remap)
        episodes.append(ep)
    if not episodes:
        high = max(remaps) if remaps else 8
        if allowed:
            high = max(high, max(allowed))
        for n in range(1, high + 1):
            ep = {"n": n, "title": f"Episode {n}"}
            if allowed is not None and n not in allowed:
                ep["skip"] = True
            remap = remaps.get(n)
            if remap is not None:
                apply_remap(ep, remap)
            episodes.append(ep)
    episodes.sort(key=lambda row: row["n"])
    dest = (
        season_obj.to_season
        if season_obj.to_season is not None
        else season_obj.dropout
    )
    return {
        "dropout": season_obj.dropout,
        "title": season_obj.title
        or (
            "Specials"
            if dest == 0
            else f"Season {season_obj.dropout or dest or 1}"
        ),
        "toSeason": dest,
        "enabled": season_obj.enabled,
        "episodes": episodes,
    }


def youtube_map_sources(playlists, by_season: dict[int, list]) -> list[dict]:
    rows = []
    for idx, playlist in enumerate(playlists, start=1):
        n = playlist.season or idx
        dest_eps = by_season.get(n, [])
        skip = set(playlist.skip or ())
        episodes = []
        if dest_eps:
            for ep in dest_eps:
                row = {"n": ep["n"], "title": ep["title"]}
                if str(ep["n"]) in skip or ep["title"] in skip:
                    row["skip"] = True
                episodes.append(row)
        else:
            episodes = [{"n": i, "title": f"Episode {i}"} for i in range(1, 9)]
        rows.append(
            {
                "url": playlist.url,
                "seasons": [
                    {
                        "dropout": n,
                        "title": playlist.title or f"Season {n}",
                        "toSeason": n,
                        "enabled": playlist.enabled,
                        "episodes": episodes,
                    }
                ],
            }
        )
    return rows


def build_shows() -> list[dict]:
    sys.path.insert(0, str(ROOT / "src"))
    from yt_dlp_emby.library import episode_title_from_filename, index_series_mkvs
    from yt_dlp_emby.server.series import (
        _iter_dropout_entries,
        _iter_youtube_entries,
        list_series,
    )

    sonarr = load_sonarr()
    dropout_cache = load_dropout_cache()
    listing = {row["slug"]: row for row in list_series(DATA, environ={})["series"]}
    shows: list[dict] = []

    for loc, series in _iter_dropout_entries(DATA):
        titles_for_season: dict[int, list[str]] = defaultdict(list)
        map_sources: list[dict] = []
        skip_pairs = set(series.tvdb_skip)

        for source in series.sources:
            season_rows: list[dict] = []
            for season_obj in source.seasons:
                dest_n = (
                    season_obj.to_season
                    if season_obj.to_season is not None
                    else season_obj.dropout
                )
                if season_obj.title and dest_n is not None:
                    titles_for_season[int(dest_n)].append(season_obj.title)
                season_rows.append(
                    map_season_row(source, season_obj, dropout_cache)
                )
            map_sources.append(
                {
                    "url": source.url
                    or next(
                        (season.url for season in source.seasons if season.url),
                        "",
                    ),
                    "seasons": season_rows,
                }
            )

        dest: dict[tuple[int, int], dict] = {}
        cache = sonarr.get(str(series.tvdb_id), {}) if series.tvdb_id else {}
        for item in cache.get("episodes") or []:
            s, e = int(item["season"]), int(item["episode"])
            skipped = (s, e) in skip_pairs
            dest[(s, e)] = {
                "n": e,
                "title": str(item.get("title") or f"E{e}"),
                "status": fictional_status(loc.slug, s, e, skipped),
            }

        seasons_out = []
        by_season: dict[int, list] = defaultdict(list)
        for (s, _e), ep in dest.items():
            by_season[s].append(ep)
        for n in sorted(by_season):
            eps = sorted(by_season[n], key=lambda ep: ep["n"])
            label, folder = dest_meta(n, titles_for_season.get(n, []))
            seasons_out.append(
                {
                    "n": n,
                    "id": f"{loc.slug}-s{n}",
                    "label": label,
                    "folder": folder,
                    "episodes": eps,
                }
            )

        meta = listing[loc.slug]
        shows.append(
            {
                "id": loc.slug,
                "name": series.name,
                "letter": letter_for(series.name),
                "tone": TONES[len(shows) % len(TONES)],
                "platform": "dropout",
                "path": f"Dropout / {series.path}",
                "tvdbId": series.tvdb_id,
                "sourceCount": meta["source_count"],
                "yamlSeasons": meta["season_count"],
                "seasons": seasons_out,
                "sources": map_sources,
                "tvdbSkip": [
                    {
                        "season": s,
                        "episodes": sorted(e for ss, e in skip_pairs if ss == s),
                    }
                    for s in sorted({p[0] for p in skip_pairs})
                ],
            }
        )

    for loc, series in _iter_youtube_entries(DATA):
        folder = series.path or series.name
        library = Path("/mnt/nas/video/Youtube") / folder
        by_season: dict[int, list] = defaultdict(list)
        if library.is_dir():
            for (s, e), path in index_series_mkvs(library).items():
                by_season[s].append(
                    {
                        "n": e,
                        "title": episode_title_from_filename(path.name),
                        "status": fictional_status(loc.slug, s, e, False),
                    }
                )
        if not by_season:
            for idx, pl in enumerate(series.playlists, start=1):
                n = pl.season or idx
                by_season[n] = [
                    {
                        "n": i,
                        "title": f"Episode {i}",
                        "status": fictional_status(loc.slug, n, i, False),
                    }
                    for i in range(1, 21)
                ]
        seasons_out = []
        for n in sorted(by_season):
            eps = sorted(by_season[n], key=lambda ep: ep["n"])
            label, folder_name = dest_meta(n, [])
            seasons_out.append(
                {
                    "n": n,
                    "id": f"{loc.slug}-s{n}",
                    "label": label,
                    "folder": folder_name,
                    "episodes": eps,
                }
            )
        shows.append(
            {
                "id": loc.slug,
                "name": series.name,
                "letter": letter_for(series.name),
                "tone": TONES[len(shows) % len(TONES)],
                "platform": "youtube",
                "path": f"Youtube / {folder}",
                "tvdbId": series.tvdb_id,
                "sourceCount": len(series.playlists),
                "yamlSeasons": len(series.playlists),
                "seasons": seasons_out,
                "sources": youtube_map_sources(series.playlists, by_season),
                "tvdbSkip": [],
                "libraryPoster": str(library / "poster.jpg"),
            }
        )

    shows.sort(key=lambda row: row["name"].casefold())
    return shows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build fictional Cosmos mock catalog (local-only).")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--data", default=str(DATA))
    parser.add_argument("--sonarr-db", default=str(SONARR_DB))
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    global ROOT, DATA, SONARR_DB, OUT_JSON, POSTER_DIR
    ROOT = Path(args.root)
    DATA = Path(args.data)
    SONARR_DB = Path(args.sonarr_db)
    OUT_JSON = Path(args.out) if args.out else ROOT / "web/src/mockups/catalog.json"
    POSTER_DIR = ROOT / "web/public/mockups"
    POSTER_DIR.mkdir(parents=True, exist_ok=True)
    shows = build_shows()
    ids = sonarr_ids_by_tvdb()
    for show in shows:
        poster = None
        if show.get("tvdbId"):
            poster = fetch_poster(int(show["tvdbId"]), show["id"], ids)
        if not poster and show.get("libraryPoster"):
            poster = copy_library_poster(Path(show["libraryPoster"]), show["id"])
        show.pop("libraryPoster", None)
        if poster:
            show["poster"] = poster

    OUT_JSON.write_text(json.dumps(shows, ensure_ascii=False, indent=2) + "\n")
    missing = {
        s["id"]: sum(
            1
            for season in s["seasons"]
            for ep in season["episodes"]
            if ep["status"] == "missing"
        )
        for s in shows
    }
    print(f"wrote {OUT_JSON} ({len(shows)} shows) missing={missing}", file=sys.stderr)


if __name__ == "__main__":
    main()
