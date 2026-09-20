import { useEffect, useState } from "preact/hooks";
import type { SeriesEpisode, SeriesSeason, Source } from "../../api";
import {
  applySeasonToEpisode,
  fileStatus,
  formatMapsTo,
  remapKind,
} from "../../seriesView";
import { Skeleton } from "../Skeleton";

export function SeasonAccordion({
  platform,
  sourceId,
  seasonId,
  season,
  episodes,
  loading,
  refreshing,
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
  refreshing?: boolean;
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
  const remapped =
    shown?.filter((ep) => {
      const kind = remapKind(season, ep);
      return kind === "same-season" || kind === "other-season";
    }).length ?? 0;
  const skipped = shown?.filter((ep) => ep.skipped).length ?? 0;
  const showSkeleton = Boolean(refreshing || (loading && !shown));

  return (
    <div
      class={season.enabled ? "season-group" : "season-group is-disabled"}
      data-testid={`season-${sourceId}-${seasonId}`}
    >
      <div class="fold-head season-head">
        <button
          type="button"
          class="fold-main"
          aria-expanded={open}
          onClick={onToggleOpen}
        >
          <span class="show-copy">
            <span class="show-name">{season.label}</span>
            <span class="show-meta">
              {season.dropout != null ? `Dropout ${season.dropout}` : season.sublabel}
              {season.to_season != null
                ? ` → ${season.to_season === 0 ? "Specials" : `Season ${season.to_season}`}`
                : ""}
            </span>
          </span>
          {showSkeleton ? (
            <Skeleton width="7.5rem" height="0.9em" />
          ) : (
            <span class="count-chip">
              {shown ? `${shown.length} episodes` : "…"}
              {remapped ? ` · ${remapped} remapped` : ""}
              {skipped ? ` · ${skipped} skipped` : ""}
            </span>
          )}
          <span class={`twist${open ? " is-open" : ""}`} aria-hidden="true" />
        </button>
        <button
          type="button"
          class="btn-ghost"
          onClick={onToggleEnabled}
        >
          {season.enabled ? "Disable" : "Enable"}
        </button>
      </div>
      {open && (
        <div class="season-eps">
          <label class="settings-field map-title-field">
            <span class="settings-label">Display title</span>
            <input
              value={titleDraft}
              placeholder={season.label}
              onInput={(e) =>
                setTitleDraft((e.currentTarget as HTMLInputElement).value)
              }
              onBlur={() => onTitleChange(titleDraft)}
            />
          </label>
          {showSkeleton
            ? Array.from({ length: 7 }, (_, index) => (
                <div key={index} class="map-ep">
                  <Skeleton width="2.4rem" />
                  <span class="ep-copy">
                    <Skeleton width={`${70 - index * 5}%`} />
                    <Skeleton width="5rem" height="0.7em" />
                  </span>
                  <Skeleton width="4.5rem" height="1.4em" />
                </div>
              ))
            : shown?.map((ep) => {
                const kind = remapKind(season, ep);
                const dest =
                  ep.skipped
                    ? "skipped"
                    : ep.mapped_season != null && ep.mapped_episode != null
                      ? formatMapsTo(ep.mapped_season, ep.mapped_episode)
                      : "—";
                const rowClass = [
                  "map-ep",
                  ep.skipped && "is-skipped",
                  kind === "same-season" && "is-remap-same",
                  kind === "other-season" && "is-remap-other",
                ]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <div key={ep.id} class={rowClass}>
                    <span class="ep-code">
                      E{String(ep.source_episode).padStart(2, "0")}
                    </span>
                    <span class="ep-copy">
                      <span class="ep-title">{ep.mapped_title || ep.title}</span>
                      <span class="ep-code">
                        {ep.skipped
                          ? "Won't download"
                          : kind === "default"
                            ? `Lands on ${dest}`
                            : `${ep.title} → ${dest}`}
                      </span>
                    </span>
                    <span
                      class={`map-chip${
                        kind === "same-season"
                          ? " is-same"
                          : kind === "other-season"
                            ? " is-other"
                            : ""
                      }`}
                    >
                      {dest}
                    </span>
                    <button
                      type="button"
                      class="btn-ghost"
                      data-testid={`episode-skip-${ep.id}`}
                      onClick={() => onSkip(ep)}
                    >
                      {ep.skipped ? "Unskip" : "Skip"}
                    </button>
                    {platform === "dropout" && !ep.skipped && (
                      <button
                        type="button"
                        class="btn-ghost"
                        data-testid={`episode-remap-${ep.id}`}
                        onClick={() => onRemap(ep)}
                      >
                        Remap
                      </button>
                    )}
                  </div>
                );
              })}
        </div>
      )}
    </div>
  );
}
