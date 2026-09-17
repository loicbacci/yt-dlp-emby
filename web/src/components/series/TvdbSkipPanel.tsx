import { useMemo, useState } from "preact/hooks";
import { useQuery } from "@tanstack/preact-query";
import { ApiError, apiClient, type SeriesDetail } from "../../api";
import { queryKeys } from "../../queryKeys";
import {
  formatMapsTo,
  removeTvdbSkip,
  skippedTvdbRows,
} from "../../seriesView";

export function TvdbSkipPanel({
  detail,
  onChange,
}: {
  detail: SeriesDetail;
  onChange: (blocks: { season: number; episodes: number[] }[]) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [manualSeason, setManualSeason] = useState("");
  const [manualEpisode, setManualEpisode] = useState("");
  const [picked, setPicked] = useState("");
  const sonarrQuery = useQuery({
    queryKey: queryKeys.sonarrEpisodes(detail.tvdb_id ?? 0),
    queryFn: () => apiClient.getSonarrEpisodes(detail.tvdb_id as number),
    enabled: detail.tvdb_id != null,
    staleTime: 30 * 60 * 1000,
  });
  const episodes = sonarrQuery.data?.episodes ?? null;
  const error =
    sonarrQuery.error instanceof ApiError
      ? sonarrQuery.error.message
      : sonarrQuery.error instanceof Error
        ? sonarrQuery.error.message
        : null;

  const skipped = useMemo(
    () => skippedTvdbRows(detail.tvdb_skip, episodes ?? []),
    [detail.tvdb_skip, episodes],
  );

  const available = useMemo(() => {
    const hidden = new Set(
      skipped.map((row) => `${row.season}-${row.episode}`),
    );
    return (episodes ?? []).filter(
      (ep) => !hidden.has(`${ep.season}-${ep.episode}`),
    );
  }, [episodes, skipped]);

  const add = (season: number, episode: number) => {
    const next = detail.tvdb_skip.map((block) => ({
      ...block,
      episodes: [...block.episodes],
    }));
    const block = next.find((item) => item.season === season);
    if (block) {
      if (!block.episodes.includes(episode)) {
        block.episodes.push(episode);
        block.episodes.sort((a, b) => a - b);
      }
    } else {
      next.push({ season, episodes: [episode] });
    }
    onChange(next);
  };

  const addManual = () => {
    const season = Number.parseInt(manualSeason, 10);
    const episode = Number.parseInt(manualEpisode, 10);
    if (!Number.isFinite(season) || !Number.isFinite(episode)) return;
    add(season, episode);
    setManualEpisode("");
    setAdding(false);
  };

  const addPicked = () => {
    const [seasonRaw, episodeRaw] = picked.split("-");
    const season = Number.parseInt(seasonRaw, 10);
    const episode = Number.parseInt(episodeRaw, 10);
    if (!Number.isFinite(season) || !Number.isFinite(episode)) return;
    add(season, episode);
    setPicked("");
    setAdding(false);
  };

  return (
    <div>
      <h2 class="settings-heading">Hide from Sonarr check</h2>
      <p class="settings-hint">
        Does not skip downloads. Used by Dropout check only.
      </p>
      {detail.tvdb_id == null && (
        <p class="settings-hint">
          Set a TVDB id to look up episode titles, or add rows below.
        </p>
      )}
      {error && <div class="validation-error">{error}</div>}
      {skipped.length === 0 ? (
        <p class="settings-hint">No exceptions yet.</p>
      ) : (
        <ul class="skip-list">
          {skipped.map((row) => (
            <li key={`${row.season}-${row.episode}`} class="skip-list-row">
              <span>
                {formatMapsTo(row.season, row.episode)}
                {row.title ? ` ${row.title}` : ""}
              </span>
              <button
                type="button"
                class="btn-ghost"
                onClick={() =>
                  onChange(removeTvdbSkip(detail.tvdb_skip, row.season, row.episode))
                }
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      {!adding ? (
        <button
          type="button"
          class="btn-secondary"
          onClick={() => setAdding(true)}
        >
          Add exception
        </button>
      ) : (
        <div class="skip-add">
          {available.length > 0 && (
            <div class="series-toolbar">
              <select
                value={picked}
                onChange={(e) =>
                  setPicked((e.currentTarget as HTMLSelectElement).value)
                }
              >
                <option value="">Choose a Sonarr episode…</option>
                {available.map((ep) => (
                  <option
                    key={`${ep.season}-${ep.episode}`}
                    value={`${ep.season}-${ep.episode}`}
                  >
                    {formatMapsTo(ep.season, ep.episode)} {ep.title}
                  </option>
                ))}
              </select>
              <button
                type="button"
                class="btn-secondary"
                disabled={!picked}
                onClick={addPicked}
              >
                Add
              </button>
            </div>
          )}
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
            <button
              type="button"
              class="btn-ghost"
              onClick={() => setAdding(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
