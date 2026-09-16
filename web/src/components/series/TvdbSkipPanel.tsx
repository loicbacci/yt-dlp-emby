import { useEffect, useMemo, useState } from "preact/hooks";
import {
  ApiError,
  apiClient,
  type SeriesDetail,
  type SonarrEpisode,
} from "../../api";
import { seasonHeading } from "../../seriesView";

export function TvdbSkipPanel({
  detail,
  onChange,
}: {
  detail: SeriesDetail;
  onChange: (blocks: { season: number; episodes: number[] }[]) => void;
}) {
  const [episodes, setEpisodes] = useState<SonarrEpisode[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manualSeason, setManualSeason] = useState("");
  const [manualEpisode, setManualEpisode] = useState("");
  const [open, setOpen] = useState<Record<number, boolean>>({ 0: true });

  useEffect(() => {
    if (detail.tvdb_id == null) {
      setEpisodes(null);
      setError(null);
      return;
    }
    apiClient
      .getSonarrEpisodes(detail.tvdb_id)
      .then((body) => {
        setEpisodes(body.episodes);
        setError(null);
      })
      .catch((err) => {
        setEpisodes([]);
        setError(err instanceof ApiError ? err.message : "Sonarr request failed");
      });
  }, [detail.tvdb_id]);

  const skipped = useMemo(() => {
    const set = new Set<string>();
    for (const block of detail.tvdb_skip) {
      for (const ep of block.episodes) set.add(`${block.season}-${ep}`);
    }
    return set;
  }, [detail.tvdb_skip]);

  const grouped = useMemo(() => {
    const map = new Map<number, { episode: number; title?: string }[]>();
    for (const ep of episodes ?? []) {
      const list = map.get(ep.season) ?? [];
      list.push({ episode: ep.episode, title: ep.title });
      map.set(ep.season, list);
    }
    for (const block of detail.tvdb_skip) {
      const list = map.get(block.season) ?? [];
      for (const ep of block.episodes) {
        if (!list.some((item) => item.episode === ep)) {
          list.push({ episode: ep });
        }
      }
      map.set(block.season, list);
    }
    return [...map.entries()].sort((a, b) => a[0] - b[0]);
  }, [episodes, detail.tvdb_skip]);

  const toggle = (season: number, episode: number) => {
    const next = detail.tvdb_skip.map((b) => ({
      ...b,
      episodes: [...b.episodes],
    }));
    const block = next.find((b) => b.season === season);
    if (block) {
      const idx = block.episodes.indexOf(episode);
      if (idx >= 0) block.episodes.splice(idx, 1);
      else block.episodes.push(episode);
      block.episodes.sort((a, b) => a - b);
    } else {
      next.push({ season, episodes: [episode] });
    }
    onChange(next.filter((b) => b.episodes.length));
  };

  const addManual = () => {
    const season = Number.parseInt(manualSeason, 10);
    const episode = Number.parseInt(manualEpisode, 10);
    if (!Number.isFinite(season) || !Number.isFinite(episode)) return;
    toggle(season, episode);
    setManualEpisode("");
  };

  return (
    <div>
      <h2 class="settings-heading">Hide from Sonarr check</h2>
      <p class="settings-hint">
        Does not skip downloads. Used by Dropout check only.
      </p>
      {detail.tvdb_id == null && (
        <p class="settings-hint">
          Set a TVDB id to load Sonarr episodes, or add rows below.
        </p>
      )}
      {error && <div class="validation-error">{error}</div>}
      {grouped.map(([season, rows]) => (
        <div key={season} class="accordion">
          <button
            type="button"
            class="accordion-head"
            aria-expanded={Boolean(open[season])}
            onClick={() =>
              setOpen((current) => ({ ...current, [season]: !current[season] }))
            }
          >
            <span>{open[season] ? "▾" : "▸"}</span>
            <span>
              {season === 0 ? "Specials (S00)" : seasonHeading(season)}
            </span>
          </button>
          {open[season] && (
            <div class="accordion-body">
              {rows
                .sort((a, b) => a.episode - b.episode)
                .map((row) => (
                  <label key={row.episode} class="settings-field">
                    <input
                      type="checkbox"
                      checked={skipped.has(`${season}-${row.episode}`)}
                      onChange={() => toggle(season, row.episode)}
                    />{" "}
                    E{row.episode}
                    {row.title ? ` ${row.title}` : ""}
                  </label>
                ))}
            </div>
          )}
        </div>
      ))}
      <div class="series-toolbar">
        <input
          type="text"
          inputMode="numeric"
          placeholder="Season"
          value={manualSeason}
          onInput={(e) =>
            setManualSeason((e.currentTarget as HTMLInputElement).value)
          }
        />
        <input
          type="text"
          inputMode="numeric"
          placeholder="Episode"
          value={manualEpisode}
          onInput={(e) =>
            setManualEpisode((e.currentTarget as HTMLInputElement).value)
          }
        />
        <button type="button" class="btn-ghost" onClick={addManual}>
          Add
        </button>
      </div>
    </div>
  );
}
