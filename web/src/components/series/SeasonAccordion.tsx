import { Fragment } from "preact";
import { useEffect, useMemo, useState } from "preact/hooks";
import type { SeriesEpisode, SeriesSeason, Source } from "../../api";
import {
  applySeasonToEpisode,
  defaultDestSeason,
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
  destError,
  skipErrors,
  open,
  onToggleOpen,
  onToggleEnabled,
  onTitleChange,
  onDestChange,
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
  destError?: string | null;
  skipErrors?: Record<string, string>;
  open: boolean;
  onToggleOpen: () => void;
  onToggleEnabled: () => void;
  onTitleChange: (value: string) => void;
  onDestChange?: (value: string) => void;
  onSkip: (episode: SeriesEpisode) => void;
  onRemap: (episode: SeriesEpisode) => void;
}) {
  const dest = defaultDestSeason(season);
  const [titleDraft, setTitleDraft] = useState(season.title ?? "");
  const [destDraft, setDestDraft] = useState(dest == null ? "" : String(dest));

  useEffect(() => {
    setTitleDraft(season.title ?? "");
  }, [season.title]);

  useEffect(() => {
    const next = defaultDestSeason(season);
    setDestDraft(next == null ? "" : String(next));
  }, [season.to_season, season.dropout]);

  // Memoized per-episode derivations: applySeasonToEpisode + fileStatus run
  // once per episodes/season/onDisk change instead of on every parent render.
  const { shown, remapped, skipped, missing, downloaded } = useMemo(() => {
    const rows =
      episodes?.map((ep) => {
        const next = applySeasonToEpisode(season, ep);
        return { ...next, status: fileStatus(next, onDisk) };
      }) ?? null;
    const isRemapped = (ep: NonNullable<typeof rows>[number]) => {
      const kind = remapKind(season, ep);
      return kind === "same-season" || kind === "other-season";
    };
    return {
      shown: rows,
      remapped: rows?.filter(isRemapped).length ?? 0,
      skipped: rows?.filter((ep) => ep.skipped).length ?? 0,
      missing: rows?.filter((ep) => season.enabled && ep.status === "missing").length ?? 0,
      downloaded: rows?.filter((ep) => ep.status === "downloaded").length ?? 0,
    };
  }, [episodes, season, onDisk]);
  const destHint = dest == null ? "" : ` → ${dest === 0 ? "Specials" : `Season ${dest}`}`;
  const showSkeleton = Boolean(refreshing || (loading && !shown));
  const chipClass = !season.enabled
    ? ""
    : missing
      ? "is-new"
      : downloaded
        ? "is-ok"
        : shown?.length
          ? "is-empty"
          : "";

  return (
    <div
      class={season.enabled ? "season-group" : "season-group is-disabled"}
      data-testid={`season-${sourceId}-${seasonId}`}
    >
      <div class="fold-head season-head">
        <button type="button" class="fold-main" aria-expanded={open} onClick={onToggleOpen}>
          <span class="show-copy">
            <span class="season-kicker">Season</span>
            <span class="show-name">{season.label}</span>
            <span class="show-meta">
              {season.dropout != null ? `Dropout ${season.dropout}` : season.sublabel}
              {destHint}
            </span>
          </span>
          {showSkeleton ? (
            <Skeleton width="7.5rem" height="0.9em" />
          ) : (
            <span class={`count-chip ${chipClass}`.trim()}>
              {shown ? `${shown.length} episodes` : "…"}
              {missing ? ` · ${missing} missing` : ""}
              {remapped ? ` · ${remapped} remapped` : ""}
              {skipped ? ` · ${skipped} skipped` : ""}
            </span>
          )}
          <span class={`twist${open ? " is-open" : ""}`} aria-hidden="true" />
        </button>
        <button type="button" class="btn-ghost" onClick={onToggleEnabled}>
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
              onInput={(e) => setTitleDraft((e.currentTarget as HTMLInputElement).value)}
              onBlur={() => onTitleChange(titleDraft)}
            />
          </label>
          {platform === "dropout" && onDestChange && (
            <label class="settings-field map-title-field">
              <span class="settings-label">Emby season</span>
              <input
                value={destDraft}
                placeholder={season.dropout == null ? "" : String(season.dropout)}
                aria-invalid={Boolean(destError)}
                onInput={(e) => setDestDraft((e.currentTarget as HTMLInputElement).value)}
                onBlur={() => onDestChange(destDraft)}
              />
              {destError && (
                <span class="validation-error" role="alert">
                  {destError}
                </span>
              )}
            </label>
          )}
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
                const destLabel = ep.skipped
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
                  <Fragment key={ep.id}>
                    <div class={rowClass}>
                      <span class="ep-code">E{String(ep.source_episode).padStart(2, "0")}</span>
                      <span class="ep-copy">
                        <span class="ep-title">{ep.mapped_title || ep.title}</span>
                        <span class="ep-code">
                          {ep.skipped
                            ? "Won't download"
                            : kind === "default"
                              ? `Lands on ${destLabel}`
                              : `${ep.title} → ${destLabel}`}
                        </span>
                      </span>
                      <span
                        class={`map-chip${
                          kind === "same-season"
                            ? " is-same"
                            : kind === "other-season"
                              ? " is-other"
                              : ep.status === "downloaded"
                                ? " is-ok"
                                : ep.status === "missing"
                                  ? " is-new"
                                  : ""
                        }`}
                      >
                        {destLabel}
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
                    {skipErrors?.[ep.id] && (
                      <p class="validation-error ep-inline-error" role="alert">
                        {skipErrors[ep.id]}
                      </p>
                    )}
                  </Fragment>
                );
              })}
        </div>
      )}
    </div>
  );
}
