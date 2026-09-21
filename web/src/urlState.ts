export function readSearch(search = window.location.search): URLSearchParams {
  return new URLSearchParams(search);
}

export function writeSearch(
  patch: Record<string, string | null | undefined>,
  replace = true,
): void {
  const params = readSearch();
  for (const [key, value] of Object.entries(patch)) {
    if (value == null || value === "") params.delete(key);
    else params.set(key, value);
  }
  const qs = params.toString();
  const url = `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash}`;
  if (replace) history.replaceState(null, "", url);
  else history.pushState(null, "", url);
}
