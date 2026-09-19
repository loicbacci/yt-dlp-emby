import { useMemo, useState } from "preact/hooks";
import {
  embyCode,
  episodeCode,
  mapsToLabel,
  remapKind,
  seasonCounts,
  shortUrl,
  showById,
  statusCounts,
  type MockMapEpisode,
  type MockMapSeason,
  type MockMapSource,
  type MockShow,
} from "./mockCatalog";
import { MockShell, Poster, Skel, Spinner, Twist } from "./Shell";

export function ShowDetail({
  slug = "dimension-20",
  tab = "library",
  loading = "idle",
  remapOpen = false,
}: {
  slug?: string;
  tab?: "library" | "mapping";
  loading?: "idle" | "refreshing";
  remapOpen?: boolean;
}) {
  const show = showById(slug);
  const [currentTab, setCurrentTab] = useState(tab);
  const [open, setOpen] = useState(show.seasons[0]?.n ?? 0);
  const [mapOpen, setMapOpen] = useState("0-0");
  const [editingUrl, setEditingUrl] = useState<string | null>(null);
  const [sheet, setSheet] = useState(remapOpen);
  const totals = useMemo(() => statusCounts(show), [show]);
  const refreshing = loading === "refreshing";

  return (
    <MockShell current="shows">
      <div class="mock-back">‹ Shows</div>
      <div class="mock-show-hero">
        <Poster
          src={show.poster}
          letter={show.letter}
          tone={show.tone}
          size="lg"
        />
        <div class="mock-show-copy">
          <div class="mock-hero-title">
            <h1>{show.name}</h1>
            <button type="button" class="mock-ghost" disabled={refreshing}>
              {refreshing ? (
                <>
                  <Spinner />
                  Refreshing
                </>
              ) : (
                "Refresh"
              )}
            </button>
          </div>
          <p class="mock-caption">
            {show.platform === "youtube" ? "YouTube" : "Dropout"} · Saved as{" "}
            {show.path}
            {show.tvdbId ? ` [tvdbid=${show.tvdbId}]` : ""}
          </p>
          {refreshing ? (
            <div class="mock-skel-meta">
              <Skel width="6.5rem" />
              <Skel width="7rem" />
              <Skel width="6rem" />
              <Skel width="5.5rem" />
            </div>
          ) : (
            <p class="mock-show-meta">
              {show.seasons.length} seasons · {totals.library} in library ·{" "}
              {totals.missing} missing · {totals.skipped} skipped
            </p>
          )}
        </div>
      </div>
      <div class="mock-tabs" role="tablist">
        <button
          type="button"
          class={currentTab === "library" ? "mock-tab is-active" : "mock-tab"}
          onClick={() => setCurrentTab("library")}
        >
          Library
        </button>
        <button
          type="button"
          class={currentTab === "mapping" ? "mock-tab is-active" : "mock-tab"}
          onClick={() => setCurrentTab("mapping")}
        >
          Mapping
        </button>
      </div>
      {currentTab === "library" ? (
        <LibraryTab
          show={show}
          open={open}
          setOpen={setOpen}
          refreshing={refreshing}
        />
      ) : (
        <MappingTab
          show={show}
          open={mapOpen}
          setOpen={setMapOpen}
          editingUrl={editingUrl}
          setEditingUrl={setEditingUrl}
          refreshing={refreshing}
          onRemap={() => setSheet(true)}
        />
      )}
      {sheet ? (
        <RemapSheet show={show} onClose={() => setSheet(false)} />
      ) : null}
    </MockShell>
  );
}

function LibraryTab({
  show,
  open,
  setOpen,
  refreshing,
}: {
  show: MockShow;
  open: number;
  setOpen: (n: number) => void;
  refreshing: boolean;
}) {
  return (
    <>
      <p class="mock-legend">
        <span>
          <span class="mock-dot-status library" />
          In library
        </span>
        <span>
          <span class="mock-dot-status missing" />
          Missing
        </span>
        <span>
          <span class="mock-dot-status skipped" />
          Skipped
        </span>
      </p>
      {show.seasons.map((season) => {
        const counts = seasonCounts(season);
        const isOpen = open === season.n;
        return (
          <section key={season.n} class="mock-card">
            <button
              type="button"
              class="mock-card-head mock-fold"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? -1 : season.n)}
            >
              <span class="mock-show-copy">
                <span class="mock-show-name">
                  {season.n === 0 ? "Specials" : season.label}
                </span>
                <span class="mock-show-meta">{season.folder}</span>
              </span>
              {refreshing ? (
                <span class="mock-count">
                  <Skel width="8.5rem" />
                </span>
              ) : (
                <span class={`mock-count${counts.missing ? " is-new" : ""}`}>
                  {counts.missing
                    ? `${counts.missing} missing · ${counts.library} in library`
                    : counts.skipped
                      ? `${counts.library} in library · ${counts.skipped} skipped`
                      : `${counts.total} in library`}
                </span>
              )}
              <Twist open={isOpen} />
            </button>
            {isOpen ? (
              refreshing ? (
                <div class="mock-season-eps">
                  {Array.from({ length: 6 }, (_, index) => (
                    <div key={index} class="mock-ep mock-leaf">
                      <span class="mock-skel-stack">
                        <Skel width={`${58 - index * 4}%`} />
                        <Skel width="4.2rem" height="0.7em" />
                      </span>
                      <span class="mock-ep-size">
                        <Skel width="4.8rem" height="1.2em" />
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div class="mock-season-eps">
                  {season.episodes.map((ep) => (
                    <div
                      key={ep.n}
                      class={
                        ep.status === "skipped"
                          ? "mock-ep mock-leaf is-skipped"
                          : "mock-ep mock-leaf"
                      }
                    >
                      <span class={`mock-dot-status ${ep.status}`} />
                      <span>
                        <span class="mock-ep-title">{ep.title}</span>
                        <span class="mock-ep-code">
                          {episodeCode(season.n, ep.n)}
                        </span>
                      </span>
                      <span
                        class={`mock-pill ${
                          ep.status === "library"
                            ? "ok"
                            : ep.status === "missing"
                              ? "warn"
                              : ""
                        }`}
                      >
                        {ep.status === "library"
                          ? "In library"
                          : ep.status === "missing"
                            ? "Missing"
                            : "Skipped"}
                      </span>
                    </div>
                  ))}
                </div>
              )
            ) : null}
          </section>
        );
      })}
    </>
  );
}

function MappingTab({
  show,
  open,
  setOpen,
  editingUrl,
  setEditingUrl,
  refreshing,
  onRemap,
}: {
  show: MockShow;
  open: string;
  setOpen: (id: string) => void;
  editingUrl: string | null;
  setEditingUrl: (url: string | null) => void;
  refreshing: boolean;
  onRemap: () => void;
}) {
  return (
    <>
      <p class="mock-caption" style={{ marginTop: 0 }}>
        Paste a Dropout series or season URL, then remap or skip episodes so they
        land on the right Emby slot. Title-only remaps keep the same number.
      </p>
      <form
        class="mock-url-row"
        onSubmit={(event) => event.preventDefault()}
      >
        <input
          placeholder={
            show.platform === "youtube"
              ? "Paste a YouTube playlist URL"
              : "Paste a Dropout series or season URL"
          }
        />
        <button type="submit" class="mock-ghost">
          Add URL
        </button>
      </form>
      {show.sources.map((source, sourceIndex) => (
        <SourceCard
          key={`${source.url}-${sourceIndex}`}
          source={source}
          sourceIndex={sourceIndex}
          open={open}
          setOpen={setOpen}
          editing={editingUrl === source.url}
          onEdit={() =>
            setEditingUrl(editingUrl === source.url ? null : source.url)
          }
          refreshing={refreshing}
          onRemap={onRemap}
        />
      ))}
      {show.tvdbSkip.length ? (
        <section class="mock-card" style={{ padding: "14px 16px" }}>
          <h2 style={{ margin: "0 0 8px", fontSize: 15 }}>Sonarr holes to ignore</h2>
          <p class="mock-show-meta" style={{ marginBottom: 10 }}>
            These TVDB slots are not missing downloads. Used by Dropout check only.
          </p>
          <div class="mock-skel-meta">
            {show.tvdbSkip.flatMap((block) =>
              block.episodes.map((ep) => (
                <span key={`${block.season}-${ep}`} class="mock-map-chip">
                  {embyCode(block.season, ep)}
                </span>
              )),
            )}
          </div>
        </section>
      ) : null}
    </>
  );
}

function SourceCard({
  source,
  sourceIndex,
  open,
  setOpen,
  editing,
  onEdit,
  refreshing,
  onRemap,
}: {
  source: MockMapSource;
  sourceIndex: number;
  open: string;
  setOpen: (id: string) => void;
  editing: boolean;
  onEdit: () => void;
  refreshing: boolean;
  onRemap: () => void;
}) {
  return (
    <section class="mock-card">
      <div class="mock-source-head">
        {editing ? (
          <input class="mock-url-edit" defaultValue={source.url} />
        ) : (
          <span class="mock-source-url">{shortUrl(source.url)}</span>
        )}
        <button type="button" class="mock-ghost" onClick={onEdit}>
          {editing ? "Save" : "Edit"}
        </button>
        <button type="button" class="mock-ghost is-danger">
          Remove
        </button>
      </div>
      {source.seasons.map((season, seasonIndex) => {
        const id = `${sourceIndex}-${seasonIndex}`;
        const isOpen = open === id;
        const remapped = season.episodes.filter(
          (ep) => remapKind(season, ep) !== "default",
        ).length;
        const skipped = season.episodes.filter((ep) => ep.skip).length;
        return (
          <div key={id} class="mock-season-group">
            <button
              type="button"
              class="mock-season-row mock-fold"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? "" : id)}
            >
              <span class="mock-show-copy">
                <span class="mock-season-name">{season.title}</span>
                <span class="mock-show-meta">
                  Dropout {season.dropout ?? "—"}
                  {season.toSeason != null
                    ? ` → ${season.toSeason === 0 ? "Specials" : `Season ${season.toSeason}`}`
                    : ""}
                </span>
              </span>
              {refreshing ? (
                <span class="mock-count">
                  <Skel width="7.5rem" />
                </span>
              ) : (
                <span class="mock-count">
                  {season.episodes.length} episodes
                  {remapped ? ` · ${remapped} remapped` : ""}
                  {skipped ? ` · ${skipped} skipped` : ""}
                </span>
              )}
              <Twist open={isOpen} />
            </button>
            {isOpen ? (
              refreshing ? (
                <div class="mock-season-eps">
                  {Array.from({ length: 7 }, (_, index) => (
                    <div key={index} class="mock-map-ep">
                      <Skel width="2.4rem" />
                      <span class="mock-skel-stack">
                        <Skel width={`${70 - index * 5}%`} />
                        <Skel width="5rem" height="0.7em" />
                      </span>
                      <Skel width="4.5rem" height="1.4em" />
                    </div>
                  ))}
                </div>
              ) : (
                <div class="mock-season-eps">
                  {season.episodes.map((ep) => (
                    <MapEpisodeRow
                      key={ep.n}
                      season={season}
                      episode={ep}
                      onRemap={onRemap}
                    />
                  ))}
                </div>
              )
            ) : null}
          </div>
        );
      })}
    </section>
  );
}

function MapEpisodeRow({
  season,
  episode,
  onRemap,
}: {
  season: MockMapSeason;
  episode: MockMapEpisode;
  onRemap: () => void;
}) {
  const kind = remapKind(season, episode);
  const dest = mapsToLabel(season, episode);
  return (
    <div
      class={[
        "mock-map-ep",
        kind === "skip" && "is-skipped",
        kind === "same" && "is-remap-same",
        kind === "other" && "is-remap-other",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span class="mock-ep-code">E{String(episode.n).padStart(2, "0")}</span>
      <span>
        <span class="mock-ep-title">
          {episode.remapTitle || episode.title}
        </span>
        <span class="mock-ep-code">
          {kind === "skip"
            ? "Won't download"
            : kind === "default"
              ? `Lands on ${dest}`
              : `${episode.title} → ${dest}`}
        </span>
      </span>
      <span class={`mock-map-chip is-${kind}`}>{dest}</span>
      <button type="button" class="mock-match">
        {episode.skip ? "Unskip" : "Skip"}
      </button>
      {!episode.skip ? (
        <button type="button" class="mock-match" onClick={onRemap}>
          Remap
        </button>
      ) : null}
    </div>
  );
}

function RemapSheet({
  show,
  onClose,
}: {
  show: MockShow;
  onClose: () => void;
}) {
  const specials = show.seasons.find((season) => season.n === 0)?.episodes ?? [];
  const suggestions = specials.slice(0, 6);
  return (
    <div class="mock-modal-backdrop" role="presentation" onClick={onClose}>
      <form
        class="mock-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="mock-remap-title"
        onClick={(event) => event.stopPropagation()}
        onSubmit={(event) => event.preventDefault()}
      >
        <h2 id="mock-remap-title">Remap episode</h2>
        <p class="mock-caption">
          Dropout Fantasy High E18 · Fantasy High: Behind the Scenes
        </p>
        <p class="mock-show-meta" style={{ marginBottom: 12 }}>
          Pick the Emby / Sonarr slot this Dropout episode should land on. Search
          by title if the number is wrong.
        </p>
        <label class="mock-field">
          Emby season
          <input defaultValue="0" />
        </label>
        <label class="mock-field">
          Emby episode
          <input defaultValue="1" />
        </label>
        <label class="mock-field">
          Title
          <input defaultValue="Fantasy High: Behind the Scenes" />
        </label>
        <h3 class="mock-section-label">Sonarr matches</h3>
        <div class="mock-suggest">
          {suggestions.map((ep) => (
            <button key={ep.n} type="button" class="mock-suggest-row">
              <span class="mock-ep-code">{embyCode(0, ep.n)}</span>
              <span class="mock-ep-title">{ep.title}</span>
            </button>
          ))}
        </div>
        <div class="mock-modal-actions">
          <button type="button" class="mock-ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" class="mock-primary">
            Save remap
          </button>
        </div>
      </form>
    </div>
  );
}
