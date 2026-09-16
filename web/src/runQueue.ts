export type Platform = "dropout" | "youtube";

export type PlanSeason = {
  platform: Platform;
  slug: string;
  series: string;
  dest_season: number;
  season_title: string | null;
  folder: string;
  download: number;
  skip: number;
  unmapped: number;
  replace: number;
};

export type PlanItem = {
  id: string;
  action: string;
  code: string;
  title: string;
  dest_season: number;
  season_title: string | null;
  folder: string;
  size: number | null;
  series: string;
  slug: string;
  platform: Platform;
};

export type PlanFile = {
  generated_at: string | null;
  force: boolean;
  sources: Record<
    string,
    {
      ok: boolean;
      error: string | null;
      seasons: PlanSeason[];
      items: PlanItem[];
    }
  >;
};

export type QueueEpisode = PlanItem & {
  status?: "pending" | "downloading" | "done" | "failed";
};

export type QueueSeason = {
  key: string;
  destSeason: number;
  folderLabel: string;
  seasonTitle: string | null;
  platform: Platform;
  pending: QueueEpisode[];
  complete: boolean;
  download: number;
  skip: number;
};

export type CompleteSeasonSummary = {
  folderLabel: string;
  seasonTitle: string | null;
  skip: number;
};

export type QueueSeries = {
  key: string;
  name: string;
  slug: string;
  platform: Platform;
  seasons: QueueSeason[];
  completeSeasons: CompleteSeasonSummary[];
  unmapped: QueueEpisode[];
  error: string | null;
  pendingCount: number;
};

export type QueueTree = QueueSeries[];

export function itemId(platform: Platform, slug: string, code: string): string {
  return `${platform}|${slug}|${code}`;
}

function seasonKey(platform: Platform, slug: string, dest: number): string {
  return `${platform}|${slug}|${dest}`;
}

export function partitionSeasons(seasons: PlanSeason[]): {
  pending: PlanSeason[];
  complete: PlanSeason[];
} {
  const pending: PlanSeason[] = [];
  const complete: PlanSeason[] = [];
  for (const season of seasons) {
    const active = season.download + season.replace + season.unmapped;
    if (active === 0 && season.skip > 0) {
      complete.push(season);
    } else if (active === 0 && season.skip === 0) {
      complete.push(season);
    } else {
      pending.push(season);
    }
  }
  return { pending, complete };
}

export function buildTree(plan: PlanFile): QueueTree {
  const bySeries = new Map<string, QueueSeries>();
  for (const [platformName, block] of Object.entries(plan.sources ?? {})) {
    const platform = platformName as Platform;
    if (!block || block.ok === false) {
      if (block?.error) {
        const errKey = `${platform}|error`;
        bySeries.set(errKey, {
          key: errKey,
          name: platform === "dropout" ? "Dropout" : "YouTube",
          slug: "",
          platform,
          seasons: [],
          completeSeasons: [],
          unmapped: [],
          error: block.error,
          pendingCount: 0,
        });
      }
      continue;
    }
    const itemsBySeason = new Map<string, QueueEpisode[]>();
    for (const item of block.items ?? []) {
      if (item.action === "skip") continue;
      const key = seasonKey(item.platform, item.slug, item.dest_season);
      const list = itemsBySeason.get(key) ?? [];
      list.push({ ...item, status: "pending" });
      itemsBySeason.set(key, list);
    }
    const { pending: pendingSeasons, complete: completeSeasons } = partitionSeasons(
      block.seasons ?? [],
    );
    const seasonMeta = new Map<string, PlanSeason>();
    for (const s of [...pendingSeasons, ...completeSeasons]) {
      seasonMeta.set(seasonKey(s.platform, s.slug, s.dest_season), s);
    }
    const slugs = new Set<string>();
    for (const s of block.seasons ?? []) slugs.add(s.slug);
    for (const item of block.items ?? []) slugs.add(item.slug);
    for (const slug of slugs) {
      const name =
        block.seasons?.find((s) => s.slug === slug)?.series ??
        block.items?.find((i) => i.slug === slug)?.series ??
        slug;
      const seriesKey = `${platform}|${slug}`;
      let series = bySeries.get(seriesKey);
      if (!series) {
        series = {
          key: seriesKey,
          name,
          slug,
          platform,
          seasons: [],
          completeSeasons: [],
          unmapped: [],
          error: null,
          pendingCount: 0,
        };
        bySeries.set(seriesKey, series);
      }
    }
    for (const [key, episodes] of itemsBySeason) {
      const meta = seasonMeta.get(key);
      if (!meta) {
        for (const ep of episodes) {
          if (ep.action !== "unmapped") continue;
          const seriesKey = `${ep.platform}|${ep.slug}`;
          const series = bySeries.get(seriesKey);
          if (series) series.unmapped.push(ep);
        }
        continue;
      }
      const seriesKey = `${meta.platform}|${meta.slug}`;
      const series = bySeries.get(seriesKey);
      if (!series) continue;
      const downloadable = episodes.filter((e) =>
        ["download", "replace"].includes(e.action),
      );
      const unmappedOnly = episodes.filter((e) => e.action === "unmapped");
      if (unmappedOnly.length) {
        series.unmapped.push(...unmappedOnly);
      }
      const active = meta.download + meta.replace + meta.unmapped;
      const isComplete = active === 0 && meta.skip > 0;
      if (isComplete && downloadable.length === 0) continue;
      series.seasons.push({
        key,
        destSeason: meta.dest_season,
        folderLabel: meta.folder,
        seasonTitle: meta.season_title,
        platform: meta.platform,
        pending: downloadable,
        complete: isComplete,
        download: meta.download,
        skip: meta.skip,
      });
      series.pendingCount += downloadable.length;
    }
    for (const meta of completeSeasons) {
      const seriesKey = `${meta.platform}|${meta.slug}`;
      const series = bySeries.get(seriesKey);
      if (!series) continue;
      const hasPending = series.seasons.some((s) => s.key === seasonKey(meta.platform, meta.slug, meta.dest_season));
      if (hasPending) continue;
      series.completeSeasons.push({
        folderLabel: meta.folder,
        seasonTitle: meta.season_title,
        skip: meta.skip,
      });
    }
  }
  return [...bySeries.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function seriesHasQueueWork(series: QueueSeries): boolean {
  return series.pendingCount > 0 || series.unmapped.length > 0 || Boolean(series.error);
}

function norm(s: string): string {
  return s.toLowerCase();
}

function seriesMatches(series: QueueSeries, query: string): boolean {
  const q = norm(query);
  if (norm(series.name).includes(q)) return true;
  for (const season of series.seasons) {
    if (seasonMatches(season, query)) return true;
  }
  for (const ep of series.unmapped) {
    if (episodeMatches(ep, query)) return true;
  }
  return false;
}

function seasonMatches(season: QueueSeason, query: string): boolean {
  const q = norm(query);
  if (season.folderLabel && norm(season.folderLabel).includes(q)) return true;
  if (season.seasonTitle && norm(season.seasonTitle).includes(q)) return true;
  return season.pending.some((ep) => episodeMatches(ep, query));
}

function episodeMatches(ep: QueueEpisode, query: string): boolean {
  const q = norm(query);
  return norm(ep.code).includes(q) || norm(ep.title).includes(q);
}

export function visibleSeries(tree: QueueTree, query: string): QueueSeries[] {
  const q = query.trim();
  if (!q) {
    return tree.filter((s) => seriesHasQueueWork(s));
  }
  return tree.filter((s) => seriesMatches(s, q));
}

export function upToDateSeries(tree: QueueTree, query: string): QueueSeries[] {
  const q = query.trim();
  const complete = tree.filter(
    (s) => s.pendingCount === 0 && s.unmapped.length === 0 && !s.error,
  );
  if (!q) return complete;
  return complete.filter((s) => seriesMatches(s, q));
}

export function searchOpen(query: string, series: QueueSeries, season: QueueSeason): boolean {
  const q = query.trim();
  if (!q) return false;
  if (norm(series.name).includes(norm(q))) return true;
  return seasonMatches(season, q);
}

export type TriState = "none" | "some" | "all";

export function triState(selectedIds: Set<string>, childIds: string[]): TriState {
  if (!childIds.length) return "none";
  let hit = 0;
  for (const id of childIds) {
    if (selectedIds.has(id)) hit += 1;
  }
  if (hit === 0) return "none";
  if (hit === childIds.length) return "all";
  return "some";
}

export function applyCheck(
  selected: Set<string>,
  childIds: string[],
  checked: boolean,
): Set<string> {
  const next = new Set(selected);
  for (const id of childIds) {
    if (checked) next.add(id);
    else next.delete(id);
  }
  return next;
}

export function pendingIds(tree: QueueTree): string[] {
  const ids: string[] = [];
  for (const series of tree) {
    for (const season of series.seasons) {
      for (const ep of season.pending) {
        if (["download", "replace"].includes(ep.action)) ids.push(ep.id);
      }
    }
  }
  return ids;
}

export function effectiveDownloadIds(
  selected: Set<string>,
  allPending: string[],
): string[] {
  if (selected.size === 0) return allPending;
  const pendingSet = new Set(allPending);
  return [...selected].filter((id) => pendingSet.has(id));
}

export function downloadLabel(effectiveCount: number): string {
  return `Download ${effectiveCount}`;
}

export function platformLabel(platform: Platform): string {
  return platform === "youtube" ? "YouTube" : "Dropout";
}

export function formatItemSize(bytes: number | null | undefined): string | null {
  if (bytes == null || bytes <= 0 || !Number.isFinite(bytes)) return null;
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  const digits = value >= 10 || index === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[index]}`;
}

export function needsConfirm(count: number): boolean {
  return count >= 25;
}

export function sourcesFor(ids: string[], tree: QueueTree): Platform[] {
  const platforms = new Set<Platform>();
  if (!ids.length) {
    for (const s of tree) {
      if (s.pendingCount > 0) platforms.add(s.platform);
    }
  } else {
    for (const id of ids) {
      const platform = id.split("|", 1)[0] as Platform;
      if (platform === "dropout" || platform === "youtube") platforms.add(platform);
    }
  }
  const order: Platform[] = ["dropout", "youtube"];
  return order.filter((p) => platforms.has(p));
}

export type ProgressState = {
  currentId: string | null;
  percent: number | null;
  phase: string | null;
  doneIds: Set<string>;
  failedIds: Set<string>;
};

export function applyProgress(
  tree: QueueTree,
  event: Record<string, unknown>,
): { tree: QueueTree; progress: ProgressState } {
  const kind = event.event as string | undefined;
  const progress: ProgressState = {
    currentId: null,
    percent: null,
    phase: null,
    doneIds: new Set(),
    failedIds: new Set(),
  };
  if (kind === "progress") {
    progress.currentId = (event.id as string) ?? null;
    const raw = event.percent;
    let percent: number | null = null;
    if (typeof raw === "number") {
      percent = raw;
    } else if (typeof raw === "string") {
      const cleaned = raw.replace("%", "").trim();
      const parsed = parseFloat(cleaned);
      percent = Number.isFinite(parsed) ? parsed : null;
    }
    if (percent == null && event.bytes != null && event.total) {
      const total = Number(event.total);
      const bytes = Number(event.bytes);
      if (total > 0) percent = (bytes / total) * 100;
    }
    progress.percent = percent;
    progress.phase = (event.phase as string) ?? null;
    return { tree, progress };
  }
  if (kind === "item_done") {
    const id = event.id as string;
    if (event.action === "failed") progress.failedIds.add(id);
    else progress.doneIds.add(id);
    progress.currentId = id;
    return { tree, progress };
  }
  return { tree, progress };
}

export type RunPhase =
  | "idle"
  | "planning"
  | "downloading"
  | "stopping"
  | "exited";

export function runStatsLine(
  run: { phase: RunPhase; source: string | null },
  progress: ProgressState,
  totalPending: number,
): string {
  const done = progress.doneIds.size;
  const failed = progress.failedIds.size;
  if (run.phase === "planning") {
    const src = run.source === "youtube" ? "YouTube" : "Dropout";
    return `Listing ${src}…`;
  }
  if (run.phase !== "downloading") {
    return `${totalPending} pending`;
  }
  const total = Math.max(totalPending + done, done + failed, 1);
  const src = run.source === "youtube" ? "YouTube" : "Dropout";
  const parts = [`${done}/${total} done`, `${failed} failed`, src];
  return parts.join(" · ");
}

export function heroFrom(
  run: { phase: RunPhase; source: string | null },
  tree: QueueTree,
  progress: ProgressState,
  listingSeries: string | null,
  pendingCount = 0,
): { heading: string; sub: string } {
  if (run.phase === "planning") {
    const src = run.source === "youtube" ? "YouTube" : "Dropout";
    const name = listingSeries ?? "…";
    return { heading: `Listing ${src}`, sub: name };
  }
  if (run.phase === "stopping") {
    return { heading: "Stopping", sub: listingSeries ?? "" };
  }
  if (run.phase === "downloading" && progress.currentId) {
    for (const series of tree) {
      for (const season of series.seasons) {
        for (const ep of season.pending) {
          if (ep.id === progress.currentId) {
            const title = season.seasonTitle ?? season.folderLabel;
            return {
              heading: `${series.name} · ${title}`,
              sub: `${ep.code} ${ep.title} · ${season.folderLabel}`,
            };
          }
        }
      }
    }
    return { heading: "Downloading", sub: listingSeries ?? "" };
  }
  if (run.phase === "downloading") {
    return { heading: "Downloading", sub: listingSeries ?? "Starting…" };
  }
  if (pendingCount > 0) {
    return {
      heading: "Ready",
      sub: `${pendingCount} episode${pendingCount === 1 ? "" : "s"} pending`,
    };
  }
  return { heading: "Up to date", sub: "Nothing waiting to download" };
}

export function groupByDestSeason<T extends { dest_season: number }>(
  episodes: T[],
): { dest_season: number; episodes: T[] }[] {
  const groups = new Map<number, T[]>();
  for (const ep of episodes) {
    const list = groups.get(ep.dest_season) ?? [];
    list.push(ep);
    groups.set(ep.dest_season, list);
  }
  const keys = [...groups.keys()].sort((a, b) => {
    if (a === 0) return 1;
    if (b === 0) return -1;
    return a - b;
  });
  return keys.map((dest) => ({ dest_season: dest, episodes: groups.get(dest)! }));
}
