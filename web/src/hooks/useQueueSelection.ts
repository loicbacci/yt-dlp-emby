import { useMemo, useState } from "preact/hooks";
import { applyCheck, effectiveDownloadIds } from "../runQueue";

function splitParam(value: string | null): string[] {
  if (!value || value === "none") return [];
  return value.split(",").filter(Boolean);
}

export function useQueueSelection(initialSel: string | null = null) {
  const [selected, setSelected] = useState<Set<string>>(() => new Set(splitParam(initialSel)));
  const [touched, setTouched] = useState(initialSel != null);

  const apply = (ids: string[], checked: boolean) => {
    setTouched(true);
    setSelected((current) => applyCheck(current, ids, checked));
  };

  const clear = () => {
    setTouched(true);
    setSelected(new Set());
  };

  const effective = (allPending: string[]) =>
    effectiveDownloadIds(selected, allPending, {
      cleared: touched && selected.size === 0,
    });

  return { selected, touched, apply, clear, setSelected, setTouched, effective };
}

export function useExpandedSeasons(
  initialOpen: string | null = null,
  initialSeasons: string | null = null,
) {
  const [openSeries, setOpenSeries] = useState<Set<string>>(() => new Set(splitParam(initialOpen)));
  const [openSeasons, setOpenSeasons] = useState<Set<string>>(
    () => new Set(splitParam(initialSeasons)),
  );
  const [openUpcoming, setOpenUpcoming] = useState<Set<string>>(new Set());

  const toggleKey = (
    setter: (fn: (current: Set<string>) => Set<string>) => void,
    key: string,
    force?: boolean,
  ) => {
    setter((current) => {
      const next = new Set(current);
      const on = force ?? !next.has(key);
      if (on) next.add(key);
      else next.delete(key);
      return next;
    });
  };

  return {
    openSeries,
    openSeasons,
    openUpcoming,
    setOpenSeries,
    setOpenSeasons,
    setOpenUpcoming,
    toggleSeries: (key: string) => toggleKey(setOpenSeries, key),
    toggleSeason: (key: string) => toggleKey(setOpenSeasons, key),
    toggleUpcoming: (key: string, open: boolean) => toggleKey(setOpenUpcoming, key, open),
  };
}

export function searchParamsMemo(search: string): URLSearchParams {
  return useMemo(() => new URLSearchParams(search), [search]);
}
