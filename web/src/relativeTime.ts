const rtf =
  typeof Intl !== "undefined"
    ? new Intl.RelativeTimeFormat(undefined, { numeric: "always", style: "narrow" })
    : null;

export function formatRelativeTime(
  iso: string | null | undefined,
  now = Date.now(),
): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return null;
  const delta = Math.max(0, now - then);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (delta < minute) return "just now";
  if (!rtf) {
    if (delta < hour) return `${Math.round(delta / minute)}m ago`;
    if (delta < day) return `${Math.round(delta / hour)}h ago`;
    return `${Math.round(delta / day)}d ago`;
  }
  if (delta < hour) return rtf.format(-Math.round(delta / minute), "minute");
  if (delta < day) return rtf.format(-Math.round(delta / hour), "hour");
  return rtf.format(-Math.round(delta / day), "day");
}

export function newestRefreshIso(
  rows: {
    refreshed?: {
      listings: string | null;
      disk: string | null;
      sonarr: string | null;
    };
  }[],
): string | null {
  let best = Number.NEGATIVE_INFINITY;
  let iso: string | null = null;
  for (const row of rows) {
    for (const value of Object.values(row.refreshed ?? {})) {
      if (!value) continue;
      const then = Date.parse(value);
      if (!Number.isFinite(then) || then <= best) continue;
      best = then;
      iso = value;
    }
  }
  return iso;
}
