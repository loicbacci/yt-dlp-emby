import { useEffect, useState } from "preact/hooks";
import type { SeriesEpisode, SeriesSeason, Source } from "../../api";
import { applySeasonToEpisode, fileStatus, seasonMissingLabel } from "../../seriesView";
import { EpisodeTable } from "./EpisodeTable";
import { EpisodeTableSkeleton, Skeleton } from "../Skeleton";

export function SeasonAccordion({
  platform,
  sourceId,
  seasonId,
  season,
  episodes,
  loading,
  onDisk,
  open,
  onToggleOpen,
  onToggleEnabled,
  onTitleChange,
  onSkip,
  onRemap,
}: {
  platform: Source;
  sourceId: number;
  seasonId: number;
  season: SeriesSeason;
  episodes: SeriesEpisode[] | null;
  loading: boolean;
  onDisk: ReadonlySet<string>;
  open: boolean;
  onToggleOpen: () => void;
  onToggleEnabled: () => void;
  onTitleChange: (value: string) => void;
  onSkip: (episode: SeriesEpisode) => void;
  onRemap: (episode: SeriesEpisode) => void;
}) {
  const [titleDraft, setTitleDraft] = useState(season.title ?? "");

  useEffect(() => {
    setTitleDraft(season.title ?? "");
  }, [season.title]);

  const shown =
    episodes?.map((ep) => {
      const next = applySeasonToEpisode(season, ep);
      return { ...next, status: fileStatus(next, onDisk) };
    }) ?? null;
  const missing = shown?.filter((ep) => ep.status === "missing").length ?? 0;
  const missingLabel = shown ? seasonMissingLabel(missing) : "";

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
          onClick={onToggleOpen}
          style={{ flex: 1 }}
        >
          <span>{open ? "▾" : "▸"}</span>
          <span class={missing > 0 ? "season-has-missing" : undefined}>
            {season.label}
          </span>
          <span class="series-row-meta">{season.sublabel}</span>
          {loading && !shown ? (
            <Skeleton width="5.5rem" height="0.85em" class="season-missing-skeleton" />
          ) : (
            missingLabel && (
              <span class="season-missing-count">{missingLabel}</span>
            )
          )}
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
          {loading && !shown && <EpisodeTableSkeleton />}
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
