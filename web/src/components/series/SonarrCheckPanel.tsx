import type { DropoutCheck } from "../../api";
import type { SeriesDetail } from "../../api";
import { formatMapsTo, sonarrBadgeLabel } from "../../seriesView";
import { EpisodeTableSkeleton } from "../Skeleton";
import { EpisodeTable } from "./EpisodeTable";

export function SonarrCheckPanel({
  detail,
  check,
  checkError,
  loading,
  onSkip,
  onRemap,
}: {
  detail: SeriesDetail;
  check: DropoutCheck | null;
  checkError: string | null;
  loading: boolean;
  onSkip: (season: number, episode: number) => void;
  onRemap: (row: DropoutCheck["missing"][number]) => void;
}) {
  const missing = check?.missing ?? [];
  const warnings = check?.warnings ?? [];
  const names = check?.title_mismatches ?? [];
  const ok = Boolean(check?.ok);
  const badge = sonarrBadgeLabel(check);

  return (
    <section class="settings-section" id="sonarr-check">
      <h2 class="settings-heading sonarr-check-heading">
        Gaps vs Sonarr
        {loading && <span class="spinner" role="status" aria-label="Checking Sonarr" />}
        {!loading && badge && (
          <span class={`badge-sonarr ${badge === "ok" ? "is-ok" : "is-new"}`}>
            {badge === "ok" ? "Up to date" : badge}
          </span>
        )}
      </h2>
      <p class="settings-section-lead">
        Sonarr episodes with no file in {detail.path || "this library folder"}.
      </p>
      {loading && <EpisodeTableSkeleton rows={5} />}
      {checkError && !loading && (
        <div class="validation-error" role="alert">
          {checkError}
        </div>
      )}
      {!loading && check && ok && missing.length === 0 && (
        <p class="settings-check-ok">Mapped. Nothing missing.</p>
      )}
      {!loading && check && missing.length > 0 && (
        <EpisodeTable
          indexLabel="Slot"
          showMapsTo={false}
          rows={missing.map((row) => ({
            id: row.code,
            index: row.code || formatMapsTo(row.season, row.episode),
            title: row.title,
            status: "missing" as const,
            actions: (
              <>
                <button type="button" class="btn-ghost" onClick={() => onRemap(row)}>
                  Find episode
                </button>
                <button
                  type="button"
                  class="btn-ghost"
                  onClick={() => onSkip(row.season, row.episode)}
                >
                  Hide
                </button>
              </>
            ),
          }))}
        />
      )}
      {!loading && warnings.length > 0 && (
        <div class="sonarr-notes">
          <h3 class="settings-heading">Warnings</h3>
          <ul class="skip-list">
            {warnings.map((row, index) => (
              <li key={`${row.code}-${row.detail}-${index}`} class="skip-list-row">
                <span>
                  {row.code} {row.detail}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {!loading && names.length > 0 && (
        <div class="sonarr-notes">
          <h3 class="settings-heading">On-disk title differs</h3>
          <ul class="skip-list">
            {names.map((row, index) => (
              <li key={`${row.code}-${row.file_title}-${index}`} class="skip-list-row">
                <span>
                  {row.code} {row.file_title}{" "}
                  <span class="run-meta">(Sonarr: {row.sonarr_title})</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
