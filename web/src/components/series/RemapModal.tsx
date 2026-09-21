import { useQuery } from "@tanstack/preact-query";
import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { type SeriesEpisode, type SonarrEpisode, apiClient } from "../../api";
import { parseNonNegInt } from "../../formValidation";
import { useModal } from "../../hooks/useModal";
import { queryKeys } from "../../queryKeys";
import {
  filterSonarrEpisodes,
  formatMapsTo,
  rankSonarrRecommendations,
  remapFormDefaults,
} from "../../seriesView";
import { ConfirmModal } from "../ConfirmModal";

export type RemapFields = {
  to_season: number;
  to_episode: number;
  title: string;
};

export function RemapModal({
  tvdbId,
  episode,
  onClose,
  onSave,
  error,
}: {
  tvdbId: number | null;
  episode: SeriesEpisode;
  onClose: () => void;
  onSave: (fields: RemapFields) => void;
  error?: string | null;
}) {
  const defaults = remapFormDefaults(episode);
  const [toSeason, setToSeason] = useState(defaults.toSeason);
  const [toEpisode, setToEpisode] = useState(defaults.toEpisode);
  const [title, setTitle] = useState(defaults.title);
  const [search, setSearch] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);
  const dirty =
    toSeason !== defaults.toSeason || toEpisode !== defaults.toEpisode || title !== defaults.title;
  const requestClose = () => {
    if (dirty) setConfirmClose(true);
    else onClose();
  };
  const dialogRef = useModal<HTMLFormElement>(true, requestClose);

  const sonarrQuery = useQuery({
    queryKey: queryKeys.sonarrEpisodes(tvdbId ?? 0),
    queryFn: () => apiClient.getSonarrEpisodes(tvdbId as number),
    enabled: tvdbId != null,
    staleTime: 30 * 60 * 1000,
  });
  const allEpisodes = sonarrQuery.data?.episodes ?? [];
  const [suggestions, setSuggestions] = useState<SonarrEpisode[]>([]);
  const suggestTimer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(suggestTimer.current), []);

  // Debounced so mount + rapid title blurs coalesce into one suggest call.
  const loadSuggest = (query: string) => {
    window.clearTimeout(suggestTimer.current);
    suggestTimer.current = window.setTimeout(() => {
      if (tvdbId == null) return;
      apiClient
        .suggestSonarr(tvdbId, query)
        .then((body) => setSuggestions(body.suggestions))
        .catch(() => setSuggestions([]));
    }, 250);
  };

  useEffect(() => {
    loadSuggest(episode.mapped_title || episode.title);
  }, [tvdbId, episode.title, episode.mapped_title]);

  const applySlot = (slot: SonarrEpisode) => {
    setToSeason(String(slot.season));
    setToEpisode(String(slot.episode));
    setTitle(slot.title);
  };

  const recommendations = useMemo(
    () =>
      rankSonarrRecommendations(allEpisodes, suggestions, {
        title: episode.mapped_title || episode.title,
        mapped_season: episode.mapped_season,
        mapped_episode: episode.mapped_episode,
        source_episode: episode.source_episode,
      }),
    [
      allEpisodes,
      suggestions,
      episode.mapped_title,
      episode.title,
      episode.mapped_season,
      episode.mapped_episode,
      episode.source_episode,
    ],
  );
  const searchHits = useMemo(
    () => filterSonarrEpisodes(allEpisodes, search).slice(0, 20),
    [allEpisodes, search],
  );
  const searching = Boolean(search.trim());

  const ready = parseNonNegInt(toSeason) != null && parseNonNegInt(toEpisode) != null;

  return (
    <div class="modal-backdrop" role="presentation" onClick={requestClose}>
      <form
        class="modal remap-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="remap-title"
        ref={dialogRef}
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          const season = parseNonNegInt(toSeason);
          const ep = parseNonNegInt(toEpisode);
          if (season == null || ep == null) {
            setFieldError("Season and episode must be numbers");
            return;
          }
          onSave({
            to_season: season,
            to_episode: ep,
            title,
          });
        }}
      >
        <h2 id="remap-title" class="modal-title">
          Remap episode
        </h2>
        <p class="remap-source">
          Dropout E{episode.source_episode} {episode.title}
        </p>
        <p class="settings-hint">
          Choose the Emby / Sonarr slot this Dropout episode should land on.
        </p>
        <label class="settings-field">
          <span class="settings-label">Emby season</span>
          <input
            value={toSeason}
            onInput={(e) => setToSeason((e.currentTarget as HTMLInputElement).value)}
          />
        </label>
        <label class="settings-field">
          <span class="settings-label">Emby episode</span>
          <input
            value={toEpisode}
            onInput={(e) => setToEpisode((e.currentTarget as HTMLInputElement).value)}
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
          <>
            <label class="url-field find-source-search">
              <span class="url-field-badge">Find</span>
              <input
                type="search"
                value={search}
                placeholder="Title, SxxExx, or episode number"
                onInput={(e) => setSearch((e.currentTarget as HTMLInputElement).value)}
              />
            </label>
            {searching && (
              <div>
                <h3 class="settings-heading">Sonarr episodes</h3>
                {searchHits.length ? (
                  <div class="suggest-list">
                    {searchHits.map((slot) => (
                      <SonarrPickButton
                        key={`${slot.season}-${slot.episode}`}
                        slot={slot}
                        onSelect={applySlot}
                      />
                    ))}
                  </div>
                ) : (
                  <p class="settings-hint">No Sonarr episodes match that search.</p>
                )}
              </div>
            )}
            <div>
              <h3 class="settings-heading">Recommendations</h3>
              {sonarrQuery.isPending ? (
                <p class="settings-hint">
                  <span class="spinner" aria-hidden="true" /> Loading Sonarr episodes…
                </p>
              ) : recommendations.length ? (
                <div class="suggest-list">
                  {recommendations.map((slot) => (
                    <SonarrPickButton
                      key={`${slot.season}-${slot.episode}`}
                      slot={slot}
                      onSelect={applySlot}
                    />
                  ))}
                </div>
              ) : (
                <p class="settings-hint">No Sonarr recommendations yet.</p>
              )}
            </div>
          </>
        )}
        {(fieldError || error) && (
          <div class="validation-error" role="alert">
            {fieldError ?? error}
          </div>
        )}
        <div class="modal-actions">
          <button type="button" class="btn-ghost" onClick={requestClose}>
            Cancel
          </button>
          <button type="submit" class="btn-modal-save" disabled={!ready}>
            Save remap
          </button>
        </div>
      </form>
      {confirmClose && (
        // Stop propagation so a backdrop click on the confirm dialog does not
        // bubble to this modal's own backdrop-close handler.
        <div onClick={(e) => e.stopPropagation()}>
          <ConfirmModal
            title="Discard remap changes?"
            message="You have unsaved edits to this remap."
            confirmLabel="Discard"
            danger
            onCancel={() => setConfirmClose(false)}
            onConfirm={onClose}
          />
        </div>
      )}
    </div>
  );
}

function SonarrPickButton({
  slot,
  onSelect,
}: {
  slot: SonarrEpisode;
  onSelect: (slot: SonarrEpisode) => void;
}) {
  return (
    <button type="button" onClick={() => onSelect(slot)}>
      {formatMapsTo(slot.season, slot.episode)} {slot.title} {slot.air_date ?? ""}
    </button>
  );
}
