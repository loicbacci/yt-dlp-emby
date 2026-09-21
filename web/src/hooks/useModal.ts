import type { RefObject } from "preact";
import { useEffect, useRef } from "preact/hooks";

let modalCount = 0;

export function useModal<T extends HTMLElement>(
  open: boolean,
  onClose: () => void,
  options?: { initialRef?: RefObject<HTMLElement | null> },
): RefObject<T> {
  const dialogRef = useRef<T>(null);
  const openerRef = useRef<Element | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    openerRef.current = document.activeElement;
    modalCount += 1;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const app = document.getElementById("app");
    const dialog = dialogRef.current;
    if (app && dialog) {
      for (const child of Array.from(app.children)) {
        if (!child.contains(dialog) && child instanceof HTMLElement) {
          child.inert = true;
        }
      }
    }
    const focusTarget =
      options?.initialRef?.current ??
      dialog?.querySelector<HTMLElement>(
        "button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])",
      );
    focusTarget?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !dialog) return;
      const focusable = [
        ...dialog.querySelectorAll<HTMLElement>(
          "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])",
        ),
      ].filter((el) => !el.hasAttribute("disabled"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      modalCount = Math.max(0, modalCount - 1);
      if (modalCount === 0) document.body.style.overflow = previousOverflow;
      if (app) {
        for (const child of Array.from(app.children)) {
          if (child instanceof HTMLElement) child.inert = false;
        }
      }
      if (openerRef.current instanceof HTMLElement) openerRef.current.focus();
    };
  }, [open, options?.initialRef]);

  return dialogRef;
}
