import { useEffect, useState } from "preact/hooks";
import { ApiError, type DropoutCheck, type Run, apiClient } from "../api";
import { Header } from "../components/Header";
import { CreateSeriesModal } from "../components/series/CreateSeriesModal";
import { go } from "../nav";
import type { SeriesPlatform, SeriesSummary } from "../seriesView";
import { countLabel, emptyListMessage, filterSeries, sonarrBadgeLabel } from "../seriesView";

const idleRun: Run = {
  status: "idle",
  phase: "idle",
  source: null,
  dry_run: false,
  verbose: false,
  force: false,
  started_at: null,
  finished_at: null,
  exit_code: null,
  plan: null,
};

export function SeriesList() {
  const [run, setRun] = useState<Run>(idleRun);
  const [rows, setRows] = useState<SeriesSummary[]>([]);
  const [query, setQuery] = useState("");
  const [platform, setPlatform] = useState<SeriesPlatform | "all">("all");
  const [error, setError] = useState<string | null>(null);
  const [modal, setModal] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sonarr, setSonarr] = useState<Record<string, DropoutCheck>>({});

  const load = async () => {
    const body = await apiClient.listSeries();
    setRows(body.series);
    setLoading(false);
  };

  useEffect(() => {
    load().catch((err) => {
      setLoading(false);
      if (err instanceof ApiError && err.status === 401) go("/login");
      else setError(err instanceof Error ? err.message : "Failed to load");
    });
    const timer = window.setInterval(() => {
      apiClient.getRun().then(setRun).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const targets = rows.filter(
      (row) => row.platform === "dropout" && row.tvdb_id != null,
    );
    if (!targets.length) return;
    let cancelled = false;
    Promise.all(
      targets.map((row) =>
        apiClient
          .getDropoutCheck(row.slug)
          .then((body) => ({ slug: row.slug, body }))
          .catch(() => null),
      ),
    ).then((results) => {
      if (cancelled) return;
      const next: Record<string, DropoutCheck> = {};
      for (const item of results) {
        if (item) next[item.slug] = item.body;
      }
      setSonarr(next);
    });
    return () => {
      cancelled = true;
    };
  }, [rows]);

  const filtered = filterSeries(rows, { query, platform });

  const logout = async () => {
    await apiClient.logout();
    go("/login");
  };

  const onCreate = async (body: {
    name: string;
    platform: import("../api").Source;
    path: string;
    tvdb_id: number | null;
  }) => {
    const detail = await apiClient.createSeries(body);
    setModal(false);
    go(`/series/${detail.platform}/${detail.slug}`);
  };

  return (
    <div class="series-shell">
      <Header run={run} current="series" onLogout={() => void logout()} />
      <section class="card series-card">
        <div class="series-toolbar">
          <h1 class="settings-title">Series</h1>
          <button
            type="button"
            class="btn-secondary"
            data-testid="series-add"
            onClick={() => setModal(true)}
          >
            Add series
          </button>
        </div>
        <div class="series-toolbar">
          <label class="series-search">
            <input
              type="search"
              placeholder="Search series"
              value={query}
              onInput={(e) =>
                setQuery((e.currentTarget as HTMLInputElement).value)
              }
            />
          </label>
          {(["all", "youtube", "dropout"] as const).map((chip) => (
            <button
              key={chip}
              type="button"
              class={platform === chip ? "filter-chip active" : "filter-chip"}
              aria-pressed={platform === chip}
              onClick={() => setPlatform(chip)}
            >
              {chip === "all"
                ? "All"
                : chip === "youtube"
                  ? "YouTube"
                  : "Dropout.tv"}
            </button>
          ))}
        </div>
        {error && <div class="validation-error">{error}</div>}
        {loading ? (
          <div class="empty-state">Loading…</div>
        ) : !filtered.length ? (
          <div class="empty-state">{emptyListMessage(rows.length, filtered.length)}</div>
        ) : (
          filtered.map((row) => (
            <a
              key={`${row.platform}-${row.slug}`}
              href={`/series/${row.platform}/${row.slug}`}
              class="series-row"
              data-testid={`series-row-${row.slug}`}
              onClick={(event) => {
                if (
                  event.defaultPrevented ||
                  event.button !== 0 ||
                  event.metaKey ||
                  event.ctrlKey ||
                  event.shiftKey ||
                  event.altKey
                ) {
                  return;
                }
                event.preventDefault();
                go(`/series/${row.platform}/${row.slug}`);
              }}
            >
              <div class="series-row-main">
                <div>{row.name}</div>
                <div class="series-row-meta">
                  <span>{row.path}</span>
                  {row.tvdb_id != null && <span>tvdb {row.tvdb_id}</span>}
                  <span>
                    {countLabel(
                      row.source_count,
                      row.platform === "youtube" ? "playlist" : "url",
                      row.platform === "youtube" ? "playlists" : "urls",
                    )}
                  </span>
                  <span>{countLabel(row.season_count, "season", "seasons")}</span>
                  {row.inline && <span>inline</span>}
                </div>
              </div>
              <div class="series-row-badges">
                {row.platform === "dropout" && row.tvdb_id != null && (
                  <a
                    class={`badge-sonarr${
                      sonarrBadgeLabel(sonarr[row.slug]) === "ok"
                        ? " is-ok"
                        : sonarr[row.slug]?.missing.length
                          ? " is-missing"
                          : ""
                    }`}
                    href={`/series/dropout/${row.slug}#sonarr-check`}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      go(`/series/dropout/${row.slug}#sonarr-check`);
                    }}
                  >
                    {sonarrBadgeLabel(sonarr[row.slug]) ?? "Sonarr"}
                  </a>
                )}
                <span
                  class={
                    row.platform === "youtube" ? "badge-youtube" : "badge-dropout"
                  }
                >
                  {row.platform === "youtube" ? "YouTube" : "Dropout.tv"}
                </span>
              </div>
            </a>
          ))
        )}
      </section>
      {modal && (
        <CreateSeriesModal
          existing={rows}
          onClose={() => setModal(false)}
          onCreate={onCreate}
        />
      )}
    </div>
  );
}
