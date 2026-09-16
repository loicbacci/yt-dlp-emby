import { useEffect, useState } from "preact/hooks";
import { apiClient, type SeriesEpisode, type SeriesSeason, type Source } from "../../api";
import { applySeasonToEpisode } from "../../seriesView";
import { EpisodeTable } from "./EpisodeTable";

export function SeasonAccordion({
  platform,
  slug,
  sourceId,
  seasonId,
  season,
  onToggleEnabled,
  onTitleChange,
  onSkip,
  onRemap,
}: {
  platform: Source;
  slug: string;
  sourceId: number;
  seasonId: number;
  season: SeriesSeason;
  onToggleEnabled: () => void;
  onTitleChange: (value: string) => void;
  onSkip: (episode: SeriesEpisode) => void;
  onRemap: (episode: SeriesEpisode) => void;
}) {
  const [open, setOpen] = useState(false);
  const [episodes, setEpisodes] = useState<SeriesEpisode[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [titleDraft, setTitleDraft] = useState(season.title ?? "");

  useEffect(() => {
    setTitleDraft(season.title ?? "");
  }, [season.title]);

  useEffect(() => {
    if (!open || episodes) return;
    setLoading(true);
    apiClient
      .getSeriesEpisodes(platform, slug, sourceId, seasonId)
      .then((body) => setEpisodes(body.episodes))
      .catch(() => setEpisodes([]))
      .finally(() => setLoading(false));
  }, [open, episodes, platform, slug, sourceId, seasonId]);

  const shown = episodes?.map((ep) => applySeasonToEpisode(season, ep)) ?? null;
  const countLabel = loading ? "…" : shown ? `${shown.length} eps` : "";

  return (
    <div
      class={season.enabled ? "accordion" : "accordion is-disabled"}
      data-testid={`season-${sourceId}-${seasonId}`}
    >
      <div class="source-head">
        <button
          type="button"
          class="accordion-head"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          style={{ flex: 1 }}
        >
          <span>{open ? "▾" : "▸"}</span>
          <span>{season.label}</span>
          <span class="series-row-meta">{season.sublabel}</span>
          <span class="series-row-meta">{countLabel}</span>
        </button>
        <button
          type="button"
          class="btn-ghost"
          style={{ marginLeft: "auto" }}
          onClick={onToggleEnabled}
        >
          {season.enabled ? "Disable" : "Enable"}
        </button>
      </div>
      {open && (
        <div class="accordion-body">
          <label class="settings-field">
            <span class="settings-label">Display title</span>
            <span class="settings-hint">
              Shown in the app. Files still use Season {season.to_season}.
            </span>
            <input
              value={titleDraft}
              placeholder={season.label}
              onInput={(e) =>
                setTitleDraft((e.currentTarget as HTMLInputElement).value)
              }
              onBlur={() => onTitleChange(titleDraft)}
            />
          </label>
          {shown && (
          <EpisodeTable
            platform={platform}
            episodes={shown}
            onSkip={onSkip}
            onRemap={onRemap}
          />
          )}
        </div>
      )}
    </div>
  );
}
