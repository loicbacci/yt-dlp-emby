import { useCallback } from "preact/hooks";

export function moveRovingIndex(
  event: KeyboardEvent,
  count: number,
  current: number,
): number | null {
  if (count <= 0) return null;
  if (event.key === "ArrowRight" || event.key === "ArrowDown") {
    event.preventDefault();
    return (current + 1) % count;
  }
  if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
    event.preventDefault();
    return (current - 1 + count) % count;
  }
  if (event.key === "Home") {
    event.preventDefault();
    return 0;
  }
  if (event.key === "End") {
    event.preventDefault();
    return count - 1;
  }
  return null;
}

export function useRovingKeys(count: number, current: number, onChange: (index: number) => void) {
  return useCallback(
    (event: KeyboardEvent) => {
      const next = moveRovingIndex(event, count, current);
      if (next != null) onChange(next);
    },
    [count, current, onChange],
  );
}
