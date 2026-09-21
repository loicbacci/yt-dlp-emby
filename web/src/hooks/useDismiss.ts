import type { RefObject } from "preact";
import { useEffect, useRef } from "preact/hooks";

export function useDismiss(
  open: boolean,
  onClose: () => void,
  selector: string,
  triggerRef?: RefObject<HTMLElement | null>,
): void {
  const openerRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    // Capture the trigger (explicit ref wins, else focused element at open time).
    openerRef.current =
      (triggerRef?.current as HTMLElement | null) ??
      (document.activeElement instanceof HTMLElement ? document.activeElement : null);
    const onPointer = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest(selector)) return;
      // Outside-pointer close: leave focus where the user clicked.
      openerRef.current = null;
      onCloseRef.current();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      const target = (triggerRef?.current as HTMLElement | null) ?? openerRef.current;
      onCloseRef.current();
      // Return focus to the trigger after the menu unmounts.
      requestAnimationFrame(() => {
        if (target && target.isConnected) target.focus();
      });
    };
    window.addEventListener("pointerdown", onPointer);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onPointer);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, selector, triggerRef]);
}
