import { useEffect, useState } from "preact/hooks";
import { apiClient, type SeriesEpisode, type SonarrEpisode } from "../../api";
import { formatMapsTo } from "../../seriesView";

export function RemapModal({
  tvdbId,
  episode,
  onClose,
  onSave,
}: {
  tvdbId: number | null;
  episode: SeriesEpisode;
  onClose: () => void;
  onSave: (fields: { to_season: number; to_episode: number; title: string }) => void;
}) {
  const [toSeason, setToSeason] = useState("");
  const [toEpisode, setToEpisode] = useState("");
  const [title, setTitle] = useState(episode.title);
  const [suggestions, setSuggestions] = useState<SonarrEpisode[]>([]);

  const loadSuggest = (query: string) => {
    if (tvdbId == null) return;
    apiClient
      .suggestSonarr(tvdbId, query)
      .then((body) => setSuggestions(body.suggestions))
      .catch(() => setSuggestions([]));
  };

  useEffect(() => {
    loadSuggest(episode.title);
  }, [tvdbId, episode.title]);

  const ready =
    toSeason.trim() !== "" &&
    toEpisode.trim() !== "" &&
    Number.isFinite(Number.parseInt(toSeason, 10)) &&
    Number.isFinite(Number.parseInt(toEpisode, 10));

  return (
    <div class="modal-backdrop" role="presentation" onClick={onClose}>
      <div class="modal" onClick={(e) => e.stopPropagation()}>
        <h2 class="modal-title">Remap episode</h2>
        <p>
          Dropout E{episode.source_episode} {episode.title}
        </p>
        <label class="settings-field">
          <span class="settings-label">Emby season</span>
          <input
            value={toSeason}
            onInput={(e) =>
              setToSeason((e.currentTarget as HTMLInputElement).value)
            }
          />
        </label>
        <label class="settings-field">
          <span class="settings-label">Emby episode</span>
          <input
            value={toEpisode}
            onInput={(e) =>
              setToEpisode((e.currentTarget as HTMLInputElement).value)
            }
          />
        </label>
        <label class="settings-field">
          <span class="settings-label">Title</span>
          <input
            value={title}
            onInput={(e) => setTitle((e.currentTarget as HTMLInputElement).value)}
            onBlur={() => loadSuggest(title)}
          />
        </label>
        {tvdbId != null && (
          <div>
            <h3 class="settings-heading">Sonarr matches</h3>
            {suggestions.length ? (
              <div class="suggest-list">
                {suggestions.map((s) => (
                  <button
                    key={`${s.season}-${s.episode}`}
                    type="button"
                    onClick={() => {
                      setToSeason(String(s.season));
                      setToEpisode(String(s.episode));
                      setTitle(s.title);
                    }}
                  >
                    {formatMapsTo(s.season, s.episode)} {s.title} {s.air_date ?? ""}
                  </button>
                ))}
              </div>
            ) : (
              <p class="settings-hint">No Sonarr title matches.</p>
            )}
          </div>
        )}
        <div class="modal-actions">
          <button type="button" class="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            class="btn-modal-save"
            disabled={!ready}
            onClick={() =>
              onSave({
                to_season: Number.parseInt(toSeason, 10),
                to_episode: Number.parseInt(toEpisode, 10),
                title,
              })
            }
          >
            Save remap
          </button>
        </div>
      </div>
    </div>
  );
}
