"""Compare Dropout library files against Sonarr episode lists."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass

from yt_dlp_emby.cache import dropout_cache_path, dropout_listings_from_cache, load_dropout_season_cache
from yt_dlp_emby.config import ConfigError, Settings
from yt_dlp_emby.dropout import resolve_emby_target
from yt_dlp_emby.dropout_manifest import DropoutManifest, DropoutSeason, DropoutSeries, season_page_url
from yt_dlp_emby.extract import DropoutListing
from yt_dlp_emby.library import emby_code, episode_title_from_filename, index_series_mkvs, title_key, titles_match
from yt_dlp_emby.sonarr import SonarrEpisode, fetch_episodes_cached, sonarr_cache_path
from yt_dlp_emby.series_ids import slugify
from yt_dlp_emby.style import bold, cyan, dim, green, red, yellow

FetchFn = Callable[[int], tuple[str, list[SonarrEpisode]]]
PlannedSlots = set[tuple[int, int]]
PlannedSeasons = set[int]
PlannedTitles = dict[tuple[int, int], tuple[str, ...]]
MappedWarning = tuple[int, int | None, str]
CachedListing = tuple[str, DropoutSeason, DropoutListing]
SonarrRef = tuple[str, SonarrEpisode]


@dataclass(frozen=True)
class Hint:
    text: str
    sure: bool
    kind: str

_STOP = frozenset({"the", "a", "an", "of", "and", "to", "for", "in", "on"})
_CUT_FOR_TIME = re.compile(r"(?:^|[^a-z0-9])season\s*(\d+)\s*:?\s*cut\s*for\s*time", re.I)


def _default_fetch(manifest: DropoutManifest, settings: Settings) -> FetchFn:
    if not settings.sonarr_url or not settings.sonarr_api_key:
        raise ConfigError(
            "dropout check needs sonarr_url and sonarr_api_key "
            "(--sonarr-url / --sonarr-api-key, YT_DLP_EMBY_SONARR_URL / "
            "YT_DLP_EMBY_SONARR_API_KEY, or config.toml)"
        )
    cache_path = sonarr_cache_path(manifest.path)

    def fetch(tvdb_id: int) -> tuple[str, list[SonarrEpisode]]:
        return fetch_episodes_cached(
            tvdb_id,
            base_url=settings.sonarr_url or "",
            api_key=settings.sonarr_api_key or "",
            cache_path=cache_path,
            force_refetch=settings.force_refetch,
        )

    return fetch


def _collect_planned(
    series: DropoutSeries,
) -> tuple[PlannedSlots, PlannedSeasons, PlannedTitles]:
    slots: PlannedSlots = set()
    seasons: PlannedSeasons = set()
    titles: dict[tuple[int, int], list[str]] = {}

    def add_slot(season: int, episode: int, title: str | None = None) -> None:
        slots.add((season, episode))
        if title:
            titles.setdefault((season, episode), []).append(title)

    for source in series.sources:
        for season in source.seasons:
            remapped: set[int] = set()
            for remap in season.remap:
                remapped.add(remap.dropout_episode)
                if remap.skip:
                    continue
                if remap.to_season is not None and remap.to_episode is not None:
                    add_slot(remap.to_season, remap.to_episode, remap.title)
            default_dest = season.to_season if season.to_season is not None else season.dropout
            if season.only_episodes is not None:
                for number in season.only_episodes:
                    if number in remapped or default_dest is None:
                        continue
                    add_slot(default_dest, number)
            elif default_dest is not None:
                seasons.add(default_dest)
    return slots, seasons, {key: tuple(values) for key, values in titles.items()}


def planned_destinations(series: DropoutSeries) -> tuple[PlannedSlots, PlannedSeasons]:
    """Emby slots the yaml would download into, without listing Dropout.

    Exact `(season, episode)` come from remaps and `only_episodes`. A default
    dest season (`to_season` or `dropout`) covers every episode in that season.
    """
    slots, seasons, _titles = _collect_planned(series)
    return slots, seasons


def _is_planned(
    season: int,
    episode: int,
    slots: PlannedSlots,
    seasons: PlannedSeasons,
) -> bool:
    return (season, episode) in slots or season in seasons


def _slot_code(season: int, episode: int | None) -> str:
    if episode is None:
        return f"S{season:02d}"
    return emby_code(season, episode)


def _mapping_warnings(
    episodes: list[SonarrEpisode],
    slots: PlannedSlots,
    seasons: PlannedSeasons,
    titles: PlannedTitles,
) -> list[MappedWarning]:
    sonarr_by_slot = {(item.season, item.episode): item for item in episodes}
    sonarr_seasons = {item.season for item in episodes}
    warnings: list[MappedWarning] = []
    unknown_slots: set[tuple[int, int]] = set()
    seen_titles: set[tuple[int, int, str]] = set()
    for slot in sorted(slots):
        yaml_titles = titles.get(slot, ())
        sonarr_ep = sonarr_by_slot.get(slot)
        if sonarr_ep is None:
            label = yaml_titles[0] if yaml_titles else None
            detail = f"{label}  not in Sonarr" if label else "not in Sonarr"
            warnings.append((slot[0], slot[1], detail))
            unknown_slots.add(slot)
            continue
        for yaml_title in yaml_titles:
            key = (slot[0], slot[1], yaml_title)
            if key in seen_titles:
                continue
            seen_titles.add(key)
            if not titles_match(yaml_title, sonarr_ep.title):
                warnings.append(
                    (slot[0], slot[1], f"{yaml_title}  (Sonarr: {sonarr_ep.title})")
                )
    for dest_season in sorted(seasons):
        if dest_season in sonarr_seasons:
            continue
        if any(season == dest_season for season, _episode in unknown_slots):
            continue
        warnings.append((dest_season, None, "not in Sonarr"))
    return warnings


def _title_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.casefold()) if token not in _STOP}


def _title_numbers(value: str) -> set[str]:
    return set(re.findall(r"\d+", value))


def titles_related(left: str, right: str) -> bool:
    """True when titles are the same, nested, or share most significant words."""
    if titles_match(left, right):
        return True
    a, b = title_key(left), title_key(right)
    if not a or not b:
        return False
    nums_a, nums_b = _title_numbers(left), _title_numbers(right)
    if nums_a and nums_b and nums_a.isdisjoint(nums_b):
        return False
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 12 and shorter in longer:
        return True
    tokens_a, tokens_b = _title_tokens(left), _title_tokens(right)
    if not tokens_a or not tokens_b:
        return False
    overlap = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return overlap >= 3 and union > 0 and overlap / union >= 0.6


def _cut_for_time_season(title: str) -> int | None:
    match = _CUT_FOR_TIME.search(title)
    if not match:
        return None
    return int(match.group(1))


def _origin_label(
    series_name: str,
    current_name: str,
    season: DropoutSeason,
    listing: DropoutListing,
) -> str:
    if season.dropout is not None:
        origin = f"season {season.dropout} E{listing.dropout_episode:02d}"
    else:
        origin = f"E{listing.dropout_episode:02d}"
    if series_name != current_name:
        return f"{series_name} {origin}"
    return origin


def _duplicate_label(
    series_name: str,
    current_name: str,
    episode: SonarrEpisode,
    on_disk: dict[str, set[tuple[int, int]]],
    *,
    sure: bool,
) -> Hint:
    code = _slot_code(episode.season, episode.episode)
    other = code if series_name == current_name else f"{series_name} {code}"
    if (episode.season, episode.episode) in on_disk.get(series_name, ()):
        text = f"add to skip list  ({other})"
    else:
        text = f"same as {other}"
    if not sure:
        text = f"maybe {text}"
    return Hint(text, sure, "duplicate")


def _is_sure_duplicate(left: SonarrEpisode, right: SonarrEpisode) -> bool:
    return bool(
        titles_match(left.title, right.title)
        and left.air_date
        and left.air_date == right.air_date
    )


def _paint_hint(hint: Hint) -> str:
    if hint.sure and hint.kind == "origin":
        return cyan(hint.text)
    if hint.sure:
        return green(hint.text)
    return yellow(hint.text)


def _cached_listings(manifest: DropoutManifest, series: DropoutSeries) -> list[CachedListing]:
    cache = load_dropout_season_cache(dropout_cache_path(manifest.path))
    found: list[CachedListing] = []
    for source in series.sources:
        for season in source.seasons:
            listings = dropout_listings_from_cache(cache.get(season_page_url(source, season)))
            if not listings:
                continue
            for listing in listings:
                found.append((series.name, season, listing))
    return found


def _missing_suggestions(
    missing: SonarrEpisode,
    current_name: str,
    catalog: list[SonarrRef],
    listings: list[CachedListing],
    on_disk: dict[str, set[tuple[int, int]]],
) -> list[Hint]:
    hints: list[Hint] = []
    seen: set[str] = set()

    def add(hint: Hint) -> None:
        if hint.text not in seen:
            seen.add(hint.text)
            hints.append(hint)

    ordered = sorted(listings, key=lambda item: item[0] != current_name)
    for series_name, season, listing in ordered:
        target = resolve_emby_target(listing, season)
        if target == "skip":
            continue
        dest_title = listing.title if target is None else target[2]
        exact = titles_match(listing.title, missing.title) or titles_match(
            dest_title, missing.title
        )
        related = titles_related(listing.title, missing.title) or titles_related(
            dest_title, missing.title
        )
        if not exact and not related:
            continue
        origin = _origin_label(series_name, current_name, season, listing)
        add(Hint(origin if exact else f"maybe {origin}", exact, "origin"))
        if target is None:
            continue
        dest_season, dest_episode, _title = target
        if series_name == current_name and (dest_season, dest_episode) == (
            missing.season,
            missing.episode,
        ):
            continue
        dest = next(
            (
                item
                for name, item in catalog
                if name == series_name
                and item.season == dest_season
                and item.episode == dest_episode
            ),
            None,
        )
        if dest is None:
            continue
        sure = _is_sure_duplicate(missing, dest)
        if sure or titles_related(dest.title, missing.title) or titles_related(
            listing.title, dest.title
        ):
            add(
                _duplicate_label(
                    series_name, current_name, dest, on_disk, sure=sure
                )
            )

    current_eps = [item for name, item in catalog if name == current_name]
    cut_season = _cut_for_time_season(missing.title)
    same_date = [
        item
        for item in current_eps
        if (item.season, item.episode) != (missing.season, missing.episode)
        and missing.air_date
        and item.air_date == missing.air_date
    ]
    for series_name, other in sorted(catalog, key=lambda item: item[0] != current_name):
        if series_name == current_name and (other.season, other.episode) == (
            missing.season,
            missing.episode,
        ):
            continue
        sure = _is_sure_duplicate(missing, other)
        if sure:
            add(_duplicate_label(series_name, current_name, other, on_disk, sure=True))
        elif titles_related(other.title, missing.title):
            add(_duplicate_label(series_name, current_name, other, on_disk, sure=False))
    if missing.season == 0 and same_date:
        mains = [item for item in same_date if item.season != 0]
        candidates = mains
        if cut_season is not None:
            in_season = [item for item in mains if item.season == cut_season]
            if in_season:
                candidates = in_season
        if len(candidates) == 1:
            other = candidates[0]
            sure = _is_sure_duplicate(missing, other)
            add(_duplicate_label(current_name, current_name, other, on_disk, sure=sure))
    hints.sort(key=lambda item: (not item.sure, item.kind != "origin"))
    return hints[:3]


def run_dropout_check(
    manifest: DropoutManifest,
    settings: Settings,
    *,
    fetch_fn: FetchFn | None = None,
) -> int:
    try:
        return _run_dropout_check(manifest, settings, fetch_fn=fetch_fn)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1


def _run_dropout_check(
    manifest: DropoutManifest,
    settings: Settings,
    *,
    fetch_fn: FetchFn | None,
) -> int:
    skipped = [series for series in manifest.series if series.tvdb_id is None]
    checked = [series for series in manifest.series if series.tvdb_id is not None]
    if not checked:
        print(dim(f"skipped {len(skipped)} series without tvdb_id"))
        return 0
    fetch = fetch_fn or _default_fetch(manifest, settings)
    reports: list[tuple[DropoutSeries, str, list[SonarrEpisode]]] = []
    for series in checked:
        assert series.tvdb_id is not None
        reports.append((series, *fetch(series.tvdb_id)))
    catalog: list[SonarrRef] = [
        (series.name, episode) for series, _title, episodes in reports for episode in episodes
    ]
    listings = [
        item
        for series, _title, _episodes in reports
        for item in _cached_listings(manifest, series)
    ]
    disk_indexes = {
        series.name: index_series_mkvs(settings.library / series.path)
        for series, _title, _episodes in reports
    }
    disk_files = {name: set(index) for name, index in disk_indexes.items()}
    failed = False
    for series, sonarr_title, episodes in reports:
        on_disk = disk_indexes[series.name]
        planned_slots, planned_seasons, planned_titles = _collect_planned(series)
        missing: list[SonarrEpisode] = []
        names: list[tuple[SonarrEpisode, str]] = []
        for episode in sorted(episodes, key=lambda item: (item.season, item.episode)):
            if (episode.season, episode.episode) in series.tvdb_skip:
                continue
            path = on_disk.get((episode.season, episode.episode))
            if path is None:
                if not _is_planned(
                    episode.season, episode.episode, planned_slots, planned_seasons
                ):
                    missing.append(episode)
                continue
            file_title = episode_title_from_filename(path.name)
            if not titles_match(file_title, episode.title):
                names.append((episode, file_title))
        warnings = _mapping_warnings(episodes, planned_slots, planned_seasons, planned_titles)
        series_name_mismatch = not titles_match(series.name, sonarr_title)
        print(bold(series.name))
        if not missing and not names and not warnings and not series_name_mismatch:
            print(f"  {green('ok')}")
            continue
        failed = True
        if series_name_mismatch:
            print(f"  {yellow('series name')}  {series.name}  (Sonarr: {sonarr_title})")
        if missing:
            print(f"  {red('missing')}")
            for episode in missing:
                line = f"    {_slot_code(episode.season, episode.episode)}  {episode.title}"
                hints = _missing_suggestions(
                    episode, series.name, catalog, listings, disk_files
                )
                if hints:
                    painted = [_paint_hint(item) for item in hints]
                    line += f"  {dim('(')}{dim('; ').join(painted)}{dim(')')}"
                print(line)
        if warnings:
            print(f"  {yellow('warning')}")
            for season, episode, detail in warnings:
                print(f"    {_slot_code(season, episode)}  {detail}")
        if names:
            print(f"  {yellow('names')}")
            for episode, file_title in names:
                print(
                    f"    {_slot_code(episode.season, episode.episode)}  {file_title}  "
                    f"(Sonarr: {episode.title})"
                )
    if skipped:
        print(dim(f"skipped {len(skipped)} series without tvdb_id"))
    return 1 if failed else 0


def _hint_to_dict(hint: Hint) -> dict[str, object]:
    return {"text": hint.text, "kind": hint.kind, "sure": hint.sure}


def check_series_report(
    manifest: DropoutManifest,
    settings: Settings,
    slug: str,
    *,
    series: DropoutSeries | None = None,
    fetch_fn: FetchFn | None = None,
) -> dict[str, object]:
    if series is None:
        series = next(
            (item for item in manifest.series if slugify(item.name) == slug),
            None,
        )
    if series is None:
        raise ConfigError("series not found")
    if series.tvdb_id is None:
        raise ConfigError("tvdb_id not set")
    if not _cached_listings(manifest, series):
        raise ConfigError("List seasons first")
    fetch = fetch_fn or _default_fetch(manifest, settings)
    sonarr_title, episodes = fetch(series.tvdb_id)
    catalog: list[SonarrRef] = [(series.name, episode) for episode in episodes]
    listings = _cached_listings(manifest, series)
    on_disk = index_series_mkvs(settings.library / series.path)
    disk_files = {series.name: set(on_disk)}
    planned_slots, planned_seasons, planned_titles = _collect_planned(series)
    missing: list[dict[str, object]] = []
    title_mismatches: list[dict[str, object]] = []
    for episode in sorted(episodes, key=lambda item: (item.season, item.episode)):
        if (episode.season, episode.episode) in series.tvdb_skip:
            continue
        path = on_disk.get((episode.season, episode.episode))
        if path is None:
            if not _is_planned(
                episode.season, episode.episode, planned_slots, planned_seasons
            ):
                hints = _missing_suggestions(
                    episode, series.name, catalog, listings, disk_files
                )
                missing.append(
                    {
                        "season": episode.season,
                        "episode": episode.episode,
                        "title": episode.title,
                        "code": _slot_code(episode.season, episode.episode),
                        "hints": [_hint_to_dict(h) for h in hints],
                    }
                )
            continue
        file_title = episode_title_from_filename(path.name)
        if not titles_match(file_title, episode.title):
            title_mismatches.append(
                {
                    "season": episode.season,
                    "episode": episode.episode,
                    "sonarr_title": episode.title,
                    "file_title": file_title,
                    "code": _slot_code(episode.season, episode.episode),
                }
            )
    warnings = [
        {
            "season": season,
            "episode": episode,
            "detail": detail,
            "code": _slot_code(season, episode),
        }
        for season, episode, detail in _mapping_warnings(
            episodes, planned_slots, planned_seasons, planned_titles
        )
    ]
    series_name_mismatch = not titles_match(series.name, sonarr_title)
    ok = (
        not missing
        and not title_mismatches
        and not warnings
        and not series_name_mismatch
    )
    return {
        "ok": ok,
        "series_name_mismatch": series_name_mismatch,
        "sonarr_title": sonarr_title,
        "missing": missing,
        "warnings": warnings,
        "title_mismatches": title_mismatches,
    }
