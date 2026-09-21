import type { PlanFile, PlanItem, PlanSeason, Source as Platform } from "./types";

export type { PlanFile, PlanItem, PlanSeason, Platform };

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
  destSeason?: number;
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
    const active =
      season.download +
      season.replace +
      season.unmapped +
      (season.rename ?? 0) +
      (season.remove ?? 0);
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
    const ownSeasons = (block.seasons ?? []).filter((s) => !s.platform || s.platform === platform);
    const ownItems = (block.items ?? []).filter(
      (item) => !item.platform || item.platform === platform,
    );
    const itemsBySeason = new Map<string, QueueEpisode[]>();
    for (const item of ownItems) {
      if (item.action === "skip") continue;
      const key = seasonKey(platform, item.slug, item.dest_season);
      const list = itemsBySeason.get(key) ?? [];
      list.push({ ...item, status: "pending" });
      itemsBySeason.set(key, list);
    }
    const { pending: pendingSeasons, complete: completeSeasons } = partitionSeasons(ownSeasons);
    const seasonMeta = new Map<string, PlanSeason>();
    for (const s of [...pendingSeasons, ...completeSeasons]) {
      seasonMeta.set(seasonKey(platform, s.slug, s.dest_season), s);
    }
    const slugs = new Set<string>();
    for (const s of ownSeasons) slugs.add(s.slug);
    for (const item of ownItems) slugs.add(item.slug);
    for (const slug of slugs) {
      const name =
        ownSeasons.find((s) => s.slug === slug)?.series ??
        ownItems.find((i) => i.slug === slug)?.series ??
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
          const seriesKey = `${platform}|${ep.slug}`;
          const series = bySeries.get(seriesKey);
          if (!series) continue;
          if (!series.unmapped.some((existing) => existing.id === ep.id)) {
            series.unmapped.push(ep);
          }
        }
        continue;
      }
      const seriesKey = `${platform}|${meta.slug}`;
      const series = bySeries.get(seriesKey);
      if (!series) continue;
      const downloadable = episodes.filter((e) =>
        ["download", "replace", "rename", "remove"].includes(e.action),
      );
      const unmappedOnly = episodes.filter((e) => e.action === "unmapped");
      if (unmappedOnly.length) {
        const seenUnmapped = new Set(series.unmapped.map((ep) => ep.id));
        for (const ep of unmappedOnly) {
          if (!seenUnmapped.has(ep.id)) {
            series.unmapped.push(ep);
            seenUnmapped.add(ep.id);
          }
        }
      }
      const active =
        meta.download + meta.replace + meta.unmapped + (meta.rename ?? 0) + (meta.remove ?? 0);
      const isComplete = active === 0 && meta.skip > 0;
      if (isComplete && downloadable.length === 0) continue;
      const existing = series.seasons.find((s) => s.key === key);
      if (existing) {
        const seen = new Set(existing.pending.map((ep) => ep.id));
        for (const ep of downloadable) {
          if (!seen.has(ep.id)) {
            existing.pending.push(ep);
            series.pendingCount += 1;
            seen.add(ep.id);
          }
        }
        continue;
      }
      series.seasons.push({
        key,
        destSeason: meta.dest_season,
        folderLabel: meta.folder,
        seasonTitle: meta.season_title,
        platform,
        pending: downloadable,
        complete: isComplete,
        download: meta.download,
        skip: meta.skip,
      });
      series.pendingCount += downloadable.length;
    }
    for (const meta of completeSeasons) {
      const seriesKey = `${platform}|${meta.slug}`;
      const series = bySeries.get(seriesKey);
      if (!series) continue;
      const destKey = seasonKey(platform, meta.slug, meta.dest_season);
      const hasPending = series.seasons.some((s) => s.key === destKey);
      if (hasPending) continue;
      if (series.completeSeasons.some((s) => s.folderLabel === meta.folder)) continue;
      series.completeSeasons.push({
        folderLabel: meta.folder,
        seasonTitle: meta.season_title,
        skip: meta.skip,
        destSeason: meta.dest_season,
      });
    }
  }
  for (const series of bySeries.values()) {
    sortQueueSeries(series);
  }
  return [...bySeries.values()].sort((a, b) => a.name.localeCompare(b.name));
}

export function destSortKey(season: number | null | undefined): [number, number] {
  if (season == null) return [2, 0];
  if (season === 0) return [1, 0];
  return [0, season];
}

export function episodeNumberFromCode(code: string): number {
  const match = /E(\d+)\s*$/i.exec(code.trim());
  if (!match) return 0;
  return Number(match[1]);
}

function compareDest(a: number, b: number): number {
  const [ag, av] = destSortKey(a);
  const [bg, bv] = destSortKey(b);
  return ag - bg || av - bv;
}

function sortQueueSeries(series: QueueSeries): void {
  series.seasons.sort((a, b) => compareDest(a.destSeason, b.destSeason));
  for (const season of series.seasons) {
    season.pending.sort((a, b) => episodeNumberFromCode(a.code) - episodeNumberFromCode(b.code));
  }
  series.completeSeasons.sort((a, b) =>
    compareDest(
      a.destSeason ?? destSeasonFromFolder(a.folderLabel),
      b.destSeason ?? destSeasonFromFolder(b.folderLabel),
    ),
  );
}

function destSeasonFromFolder(folder: string): number {
  if (/^specials$/i.test(folder.trim())) return 0;
  const match = /season\s+(\d+)/i.exec(folder);
  return match ? Number(match[1]) : 0;
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

export function seriesInActiveDownload(
  series: QueueSeries,
  downloadIds: ReadonlySet<string>,
): boolean {
  return series.seasons.some((season) =>
    season.pending.some((ep) => downloadIds.has(ep.id) && ep.status !== "done"),
  );
}

export function upToDateSeries(tree: QueueTree, query: string): QueueSeries[] {
  const q = query.trim();
  const complete = tree.filter((s) => s.pendingCount === 0 && s.unmapped.length === 0 && !s.error);
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

export function remainingEpisodes(season: QueueSeason, hideDone: boolean): QueueEpisode[] {
  if (!hideDone) return season.pending;
  return season.pending.filter((ep) => ep.status !== "done");
}

export function finishedEpisodes(season: QueueSeason): QueueEpisode[] {
  return season.pending.filter((ep) => ep.status === "done");
}

export function pendingIds(tree: QueueTree): string[] {
  const ids: string[] = [];
  for (const series of tree) {
    for (const season of series.seasons) {
      for (const ep of season.pending) {
        if (["download", "replace", "rename", "remove"].includes(ep.action)) ids.push(ep.id);
      }
    }
  }
  return ids;
}

export function effectiveDownloadIds(
  selected: Set<string>,
  allPending: string[],
  options?: { cleared?: boolean },
): string[] {
  if (selected.size === 0) return options?.cleared ? [] : allPending;
  const pendingSet = new Set(allPending);
  return [...selected].filter((id) => pendingSet.has(id));
}

export function downloadLabel(effectiveCount: number): string {
  return `Download ${effectiveCount} episode${effectiveCount === 1 ? "" : "s"}`;
}

const DOWNLOAD_ACTIONS = new Set(["download", "replace"]);
const RUN_ACTIONS = new Set(["download", "replace", "rename", "remove"]);

export function actionLabel(action: string): string {
  if (action === "replace") return "Replace";
  if (action === "rename") return "Rename";
  if (action === "remove") return "Remove";
  if (action === "unmapped") return "Unmapped";
  return "Download";
}

export function actionsForIds(ids: string[], tree: QueueTree): string[] {
  const wanted = new Set(ids);
  const out: string[] = [];
  for (const series of tree) {
    for (const season of series.seasons) {
      for (const ep of season.pending) {
        if (wanted.has(ep.id) && RUN_ACTIONS.has(ep.action)) out.push(ep.action);
      }
    }
  }
  return out;
}

export function isDownloadHeavy(actions: string[]): boolean {
  return actions.length === 0 || actions.every((action) => DOWNLOAD_ACTIONS.has(action));
}

export function runLabel(count: number, actions: string[]): string {
  if (isDownloadHeavy(actions)) return downloadLabel(count);
  const unique = [...new Set(actions)];
  if (unique.length === 1) {
    return `${actionLabel(unique[0] ?? "download")} ${count} episode${count === 1 ? "" : "s"}`;
  }
  return `Apply ${count} change${count === 1 ? "" : "s"}`;
}

export function queueHeading(count: number, actions: string[]): string {
  if (count === 0) return "Up to date";
  if (isDownloadHeavy(actions)) {
    return `${count} new episode${count === 1 ? "" : "s"}`;
  }
  return `${count} queued change${count === 1 ? "" : "s"}`;
}

export function countChipText(count: number, downloading: boolean, actions: string[]): string {
  if (downloading) return `${count} remaining`;
  if (isDownloadHeavy(actions)) return `${count} new`;
  return `${count} queued`;
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
  step: number | null;
  steps: string[];
  speed: number | null;
  eta: number | null;
  bytes: number | null;
  total: number | null;
  doneIds: Set<string>;
  failedIds: Set<string>;
};

export function emptyProgress(): ProgressState {
  return {
    currentId: null,
    percent: null,
    phase: null,
    step: null,
    steps: [],
    speed: null,
    eta: null,
    bytes: null,
    total: null,
    doneIds: new Set(),
    failedIds: new Set(),
  };
}

const ANSI_RE = /\u001b\[[0-9;]*m/g;

export function parseFiniteNumber(raw: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  if (typeof raw === "string") {
    const parsed = Number.parseFloat(raw.replace(ANSI_RE, "").trim());
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

export function formatBinaryBytes(num: number | null | undefined): string {
  if (num == null || !Number.isFinite(num)) return "?";
  let value = num;
  for (const unit of ["B", "KiB", "MiB", "GiB"] as const) {
    if (Math.abs(value) < 1024 || unit === "GiB") {
      return `${value.toFixed(1)}${unit}`;
    }
    value /= 1024;
  }
  return `${value.toFixed(1)}GiB`;
}

export function formatEta(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return "--:--";
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

export function formatProgressStats(progress: ProgressState): string | null {
  const parts: string[] = [];
  if (progress.phase) parts.push(progress.phase);
  if (progress.total != null && progress.total > 0) {
    parts.push(`${formatBinaryBytes(progress.bytes ?? 0)}/${formatBinaryBytes(progress.total)}`);
  } else if (progress.bytes != null && progress.bytes > 0) {
    parts.push(formatBinaryBytes(progress.bytes));
  }
  if (progress.speed != null && Number.isFinite(progress.speed)) {
    parts.push(`${formatBinaryBytes(progress.speed)}/s`);
  }
  return parts.length ? parts.join(" · ") : null;
}

export function parsePercent(raw: unknown, bytes?: unknown, total?: unknown): number | null {
  if (typeof raw === "number" && Number.isFinite(raw)) {
    return Math.min(100, Math.max(0, raw));
  }
  if (typeof raw === "string") {
    const cleaned = raw.replace(ANSI_RE, "").replace("%", "").trim();
    const parsed = Number.parseFloat(cleaned);
    if (Number.isFinite(parsed)) return Math.min(100, Math.max(0, parsed));
  }
  const totalN = Number(total);
  const bytesN = Number(bytes);
  if (totalN > 0 && Number.isFinite(bytesN)) {
    return Math.min(100, Math.max(0, (bytesN / totalN) * 100));
  }
  return null;
}

export function applyProgress(
  tree: QueueTree,
  event: Record<string, unknown>,
): { tree: QueueTree; progress: ProgressState } {
  const kind = event.event as string | undefined;
  const progress: ProgressState = emptyProgress();
  if (kind === "item_steps") {
    progress.currentId = (event.id as string) ?? null;
    progress.steps = Array.isArray(event.steps) ? (event.steps as string[]).map(String) : [];
    progress.step = 0;
    return { tree, progress };
  }
  if (kind === "progress") {
    progress.currentId = (event.id as string) ?? null;
    progress.percent = parsePercent(event.percent, event.bytes, event.total);
    progress.phase = (event.phase as string) ?? null;
    if (typeof event.step === "number") progress.step = event.step;
    if (Array.isArray(event.steps)) {
      progress.steps = (event.steps as string[]).map(String);
    }
    progress.speed = parseFiniteNumber(event.speed);
    progress.eta = parseFiniteNumber(event.eta);
    progress.bytes = parseFiniteNumber(event.bytes);
    progress.total = parseFiniteNumber(event.total);
    return { tree, progress };
  }
  if (kind === "item_done") {
    const id = event.id as string;
    if (event.action === "failed") progress.failedIds.add(id);
    else progress.doneIds.add(id);
    progress.currentId = id;
    progress.percent = event.action === "failed" ? null : 100;
    progress.step = null;
    return { tree, progress };
  }
  return { tree, progress };
}

export function mergeProgress(current: ProgressState, next: ProgressState): ProgressState {
  const isProgress =
    next.percent != null || next.speed != null || next.bytes != null || next.step != null;
  const idChanged =
    next.currentId != null && current.currentId != null && next.currentId !== current.currentId;
  const currentId = next.currentId ?? current.currentId;
  const steps = next.steps.length > 0 ? next.steps : idChanged ? [] : current.steps;
  const step = typeof next.step === "number" ? next.step : idChanged ? null : current.step;
  const percent = next.percent != null ? next.percent : idChanged ? null : current.percent;
  return {
    currentId,
    percent,
    phase: next.phase ?? current.phase,
    step,
    steps,
    speed: isProgress ? next.speed : current.speed,
    eta: isProgress ? next.eta : current.eta,
    bytes: next.bytes ?? current.bytes,
    total: next.total ?? current.total,
    doneIds: new Set([...current.doneIds, ...next.doneIds]),
    failedIds: new Set([...current.failedIds, ...next.failedIds]),
  };
}

export function overlayProgress(tree: QueueTree, progress: ProgressState): QueueTree {
  if (!progress.currentId && progress.doneIds.size === 0 && progress.failedIds.size === 0) {
    return tree;
  }
  let treeChanged = false;
  const next = tree.map((series) => {
    let seriesChanged = false;
    const seasons = series.seasons.map((season) => {
      let seasonChanged = false;
      const pending = season.pending.map((ep) => {
        let status = ep.status ?? "pending";
        if (progress.failedIds.has(ep.id)) status = "failed";
        else if (progress.doneIds.has(ep.id)) status = "done";
        else if (progress.currentId === ep.id) status = "downloading";
        else status = "pending";
        if (status === ep.status) return ep;
        seasonChanged = true;
        return { ...ep, status };
      });
      if (!seasonChanged) return season;
      seriesChanged = true;
      return { ...season, pending };
    });
    if (!seriesChanged) return series;
    treeChanged = true;
    return { ...series, seasons };
  });
  // Preserve referential identity for memoized rows when nothing changed.
  return treeChanged ? next : tree;
}

export function episodeForId(
  tree: QueueTree,
  id: string,
): { series: QueueSeries; season: QueueSeason; ep: QueueEpisode } | null {
  for (const series of tree) {
    for (const season of series.seasons) {
      for (const ep of season.pending) {
        if (ep.id === id) return { series, season, ep };
      }
    }
  }
  return null;
}

export type RunPhase = "idle" | "planning" | "downloading" | "stopping" | "exited";

/**
 * Single source for the planning-phase label. Unknown sources render a bare
 * "Listing…" (never a guessed platform) and there is no trailing ellipsis on
 * the named form. Used by runStatsLine, heroFrom, and StatusChip.
 */
export function listingLabel(source: string | null | undefined): string {
  const src = source === "youtube" ? "YouTube" : source === "dropout" ? "Dropout" : null;
  return src ? `Listing ${src}` : "Listing…";
}

export function runStatsLine(
  run: { phase: RunPhase; source: string | null },
  progress: ProgressState,
  totalPending: number,
): string {
  const done = progress.doneIds.size;
  const failed = progress.failedIds.size;
  if (run.phase === "planning") {
    return listingLabel(run.source);
  }
  if (run.phase !== "downloading") {
    return `${totalPending} pending`;
  }
  const total = Math.max(totalPending, done + failed, 1);
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
    const name = listingSeries ?? "…";
    return { heading: listingLabel(run.source), sub: name };
  }
  if (run.phase === "stopping") {
    return { heading: "Stopping", sub: listingSeries ?? "" };
  }
  if (run.phase === "downloading" && progress.currentId) {
    const hit = episodeForId(tree, progress.currentId);
    if (hit) {
      const title = hit.season.seasonTitle ?? hit.season.folderLabel;
      return {
        heading: `${hit.series.name} · ${title}`,
        sub: `${hit.ep.code} ${hit.ep.title}`,
      };
    }
    const code = progress.currentId.split("|")[2] ?? progress.currentId;
    return { heading: "Downloading", sub: code };
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
