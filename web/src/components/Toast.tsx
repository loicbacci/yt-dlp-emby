import { createStore } from "@tanstack/preact-store";
import { useSelector } from "@tanstack/preact-store";
import { useEffect } from "preact/hooks";

export type ToastKind = "status" | "alert";

export type ToastItem = {
  id: number;
  message: string;
  kind: ToastKind;
};

type ToastState = { items: ToastItem[] };

const toastStore = createStore<ToastState>({ items: [] });
let nextId = 1;

export function pushToast(message: string, kind: ToastKind = "status"): number {
  const id = nextId++;
  toastStore.setState((state) => ({ items: [...state.items, { id, message, kind }] }));
  window.setTimeout(() => dismissToast(id), 4000);
  return id;
}

export function dismissToast(id: number): void {
  toastStore.setState((state) => ({ items: state.items.filter((item) => item.id !== id) }));
}

export function useToasts(): ToastItem[] {
  return useSelector(toastStore, (state) => state.items);
}

export function ToastHost() {
  const items = useToasts();
  if (!items.length) return null;
  return (
    <div class="toast-stack" aria-live="polite">
      {items.map((item) => (
        <div
          key={item.id}
          class={`toast toast-${item.kind}`}
          role={item.kind === "alert" ? "alert" : "status"}
        >
          {item.message}
        </div>
      ))}
    </div>
  );
}

export function useDocumentTitle(title: string): void {
  useEffect(() => {
    const previous = document.title;
    document.title = title;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
