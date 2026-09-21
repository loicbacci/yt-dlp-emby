import { useMemo, useRef, useState } from "preact/hooks";
import type { DropoutCheckHint } from "../../api";
import { useModal } from "../../hooks/useModal";
import {
  type CatalogEpisode,
  applySeasonToEpisode,
  catalogEpisodeKey,
  filterCatalogEpisodes,
  formatMapsTo,
  shortUrl,
} from "../../seriesView";
import { EpisodeTableSkeleton } from "../Skeleton";

export function FindSourceModal({
  target,
  catalog,
  suggestions,
  hints = [],
  loading,
  onClose,
  onSave,
}: {
  target: { season: number; episode: number; title: string };
  catalog: CatalogEpisode[];
  suggestions: CatalogEpisode[];
  hints?: DropoutCheckHint[];
  loading?: boolean;
  onClose: () => void;
  onSave: (source: CatalogEpisode) => void;
}) {
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<CatalogEpisode | null>(null);

  const dialogRef = useModal<HTMLFormElement>(true, onClose, {
    initialRef: searchRef as unknown as import("preact").RefObject<HTMLElement | null>,
  });

  const slot = formatMapsTo(target.season, target.episode);
  const filtered = useMemo(() => filterCatalogEpisodes(catalog, query), [catalog, query]);
  const suggestedKeys = useMemo(() => new Set(suggestions.map(catalogEpisodeKey)), [suggestions]);
  const searching = Boolean(query.trim());
  const visibleSuggestions = useMemo(() => {
    const allowed = new Set(filtered.map(catalogEpisodeKey));
    return suggestions.filter((row) => allowed.has(catalogEpisodeKey(row)));
  }, [suggestions, filtered]);
  const browseRows = useMemo(() => {
    if (searching) return filtered;
    return filtered.filter((row) => !suggestedKeys.has(catalogEpisodeKey(row)));
  }, [filtered, searching, suggestedKeys]);
  const groups = useMemo(() => groupBySeason(browseRows), [browseRows]);
  const otherHints = hints.filter((hint) => hint.kind !== "origin");

  return (
    <div class="modal-backdrop" role="presentation" onClick={onClose}>
      <form
        ref={dialogRef}
        class="modal remap-modal find-source-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="find-source-title"
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => {
          event.preventDefault();
          if (!picked) return;
          onSave(picked);
        }}
      >
        <h2 id="find-source-title" class="modal-title">
          Find Dropout episode
        </h2>
        <p class="remap-source">
          {slot} {target.title}
        </p>
        <p class="settings-hint">
          This Sonarr slot has no file. Pick the Dropout episode that should map here.
        </p>
        {otherHints.length > 0 && (
          <p class="settings-hint">{otherHints.map((hint) => hint.text).join(" · ")}</p>
        )}
        <label class="url-field find-source-search">
          <span class="url-field-badge">Find</span>
          <input
            ref={searchRef}
            type="search"
            value={query}
            placeholder="Title, E number, or season"
            onInput={(e) => setQuery((e.currentTarget as HTMLInputElement).value)}
          />
        </label>
        {loading && filtered.length === 0 ? (
          <EpisodeTableSkeleton rows={6} />
        ) : (
          <div class="find-source-list">
            {!searching && visibleSuggestions.length > 0 && (
              <section>
                <h3 class="settings-heading">Suggested</h3>
                <div class="suggest-list">
                  {visibleSuggestions.map((row) => (
                    <SourcePickButton
                      key={catalogEpisodeKey(row)}
                      row={row}
                      selected={isPicked(picked, row)}
                      onSelect={setPicked}
                      onConfirm={() => onSave(row)}
                    />
                  ))}
                </div>
              </section>
            )}
            {groups.length === 0 ? (
              <p class="settings-hint">
                {catalog.length === 0
                  ? "Dropout listings are still loading. Open a season in the catalog if this stays empty."
                  : "No Dropout episodes match that search."}
              </p>
            ) : (
              groups.map((group) => (
                <section key={group.key}>
                  <h3 class="settings-heading">{group.label}</h3>
                  <div class="suggest-list">
                    {group.rows.map((row) => (
                      <SourcePickButton
                        key={catalogEpisodeKey(row)}
                        row={row}
                        selected={isPicked(picked, row)}
                        suggested={!searching && suggestedKeys.has(catalogEpisodeKey(row))}
                        onSelect={setPicked}
                        onConfirm={() => onSave(row)}
                      />
                    ))}
                  </div>
                </section>
              ))
            )}
          </div>
        )}
        <div class="modal-actions">
          <button type="button" class="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" class="btn-modal-save" disabled={!picked}>
            {picked ? `Map E${picked.episode.source_episode} here` : "Map episode here"}
          </button>
        </div>
      </form>
    </div>
  );
}

function isPicked(picked: CatalogEpisode | null, row: CatalogEpisode): boolean {
  return Boolean(picked && catalogEpisodeKey(picked) === catalogEpisodeKey(row));
}

function SourcePickButton({
  row,
  selected,
  suggested,
  onSelect,
  onConfirm,
}: {
  row: CatalogEpisode;
  selected: boolean;
  suggested?: boolean;
  onSelect: (row: CatalogEpisode) => void;
  onConfirm: () => void;
}) {
  const mapped = applySeasonToEpisode(row.season, row.episode);
  const mapsTo =
    mapped.mapped_season != null && mapped.mapped_episode != null
      ? formatMapsTo(mapped.mapped_season, mapped.mapped_episode)
      : "unmapped";
  return (
    <button
      type="button"
      class={[selected && "is-selected", suggested && "is-suggested"].filter(Boolean).join(" ")}
      onClick={() => onSelect(row)}
      onDblClick={onConfirm}
    >
      <span class="maps-to">E{row.episode.source_episode}</span> {row.episode.title}
      <span class="run-meta">
        currently {mapsTo}
        {row.sourceUrl ? ` · ${shortUrl(row.sourceUrl)}` : ""}
      </span>
    </button>
  );
}

function groupBySeason(
  rows: CatalogEpisode[],
): { key: string; label: string; rows: CatalogEpisode[] }[] {
  const groups: { key: string; label: string; rows: CatalogEpisode[] }[] = [];
  const index = new Map<string, number>();
  for (const row of rows) {
    const key = `${row.sourceId}-${row.seasonId}`;
    const existing = index.get(key);
    if (existing != null) {
      const group = groups[existing];
      if (group) group.rows.push(row);
      continue;
    }
    index.set(key, groups.length);
    const dropout = row.season.dropout != null ? `Dropout ${row.season.dropout}` : "";
    const url = row.sourceUrl ? shortUrl(row.sourceUrl) : "";
    const bits = [row.season.label, dropout, url].filter(Boolean);
    groups.push({
      key,
      label: bits.join(" · "),
      rows: [row],
    });
  }
  return groups;
}
