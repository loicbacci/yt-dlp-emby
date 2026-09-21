import { useEffect, useRef, useState } from "preact/hooks";
import { ApiError, apiClient } from "../api";
import { pushToast } from "../components/Toast";
import { go } from "../nav";
import { type ProgressState, applyProgress, emptyProgress, mergeProgress } from "../runQueue";
import type { QueueTree } from "../runQueue";

export function useRunEvents(runKey: string, treeRef: { current: QueueTree }, online: boolean) {
  const [progress, setProgress] = useState<ProgressState>(emptyProgress());
  const [listingSeries, setListingSeries] = useState<string | null>(null);
  const [eventsReconnecting, setEventsReconnecting] = useState(false);
  const progressRef = useRef(progress);
  progressRef.current = progress;
  const rafRef = useRef<number | undefined>(undefined);
  const pendingPatch = useRef<ProgressState | null>(null);

  const flushProgress = (patch: ProgressState) => {
    pendingPatch.current = pendingPatch.current
      ? mergeProgress(pendingPatch.current, patch)
      : patch;
    if (rafRef.current != null) return;
    rafRef.current = window.setTimeout(() => {
      rafRef.current = undefined;
      const next = pendingPatch.current;
      pendingPatch.current = null;
      if (next) setProgress((current) => mergeProgress(current, next));
    }, 250);
  };

  useEffect(() => {
    setProgress(emptyProgress());
    setListingSeries(null);
    setEventsReconnecting(false);
  }, [runKey]);

  useEffect(() => {
    if (!online) return;
    let source: EventSource | null = null;
    let last = 0;
    let closed = false;
    let timer: number | undefined;
    let backoff = 1000;
    let expiredToasted = false;
    const expireSession = () => {
      if (!expiredToasted) {
        expiredToasted = true;
        pushToast("Session expired", "alert");
      }
      go("/login");
    };

    const connect = () => {
      if (closed) return;
      source = new EventSource(`/api/runs/events?after=${last}`);
      source.onopen = () => {
        setEventsReconnecting(false);
      };
      source.onmessage = (message) => {
        setEventsReconnecting(false);
        backoff = 1000;
        try {
          const payload = JSON.parse(message.data) as {
            n: number;
            event: Record<string, unknown>;
          };
          last = payload.n;
          const ev = payload.event;
          if (ev.event === "series" && typeof ev.name === "string") {
            setListingSeries(ev.name);
          }
          if (ev.event === "item_steps" || ev.event === "progress" || ev.event === "item_done") {
            const { progress: next } = applyProgress(treeRef.current, ev);
            flushProgress(next);
          }
        } catch {
          /* ignore malformed events */
        }
      };
      source.onerror = () => {
        source?.close();
        if (closed) return;
        setEventsReconnecting(true);
        void apiClient
          .session()
          .then((session) => {
            if (!session.authenticated) {
              expireSession();
              return;
            }
            timer = window.setTimeout(connect, backoff);
            backoff = Math.min(backoff * 2, 8000);
          })
          .catch((err) => {
            if (err instanceof ApiError && err.status === 401) {
              expireSession();
              return;
            }
            timer = window.setTimeout(connect, backoff);
            backoff = Math.min(backoff * 2, 8000);
          });
      };
    };

    connect();
    return () => {
      closed = true;
      source?.close();
      if (timer !== undefined) window.clearTimeout(timer);
      if (rafRef.current != null) window.clearTimeout(rafRef.current);
    };
  }, [runKey, online, treeRef]);

  return {
    progress,
    setProgress,
    listingSeries,
    setListingSeries,
    eventsReconnecting,
  };
}
