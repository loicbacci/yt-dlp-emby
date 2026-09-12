import { useEffect, useRef, useState } from "preact/hooks";
import { ApiError, apiClient } from "../api";
import { go } from "../nav";

export function LogViewer({ runKey }: { runKey: string }) {
  const preRef = useRef<HTMLPreElement>(null);
  const lastNRef = useRef(0);
  const [lines, setLines] = useState<string[]>([]);
  const [reconnecting, setReconnecting] = useState(false);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    setLines([]);
    lastNRef.current = 0;
  }, [runKey]);

  useEffect(() => {
    let source: EventSource | null = null;
    let backoff = 1000;
    let closed = false;
    let timer: number | undefined;

    const connect = () => {
      if (closed) return;
      setReconnecting(lastNRef.current > 0);
      source = new EventSource(`/api/runs/log?after=${lastNRef.current}`);
      source.onmessage = (event) => {
        setReconnecting(false);
        backoff = 1000;
        try {
          const payload = JSON.parse(event.data) as { n: number; line: string };
          lastNRef.current = payload.n;
          setLines((prev) => [...prev, payload.line]);
        } catch {
          /* ignore */
        }
      };
      source.onerror = () => {
        source?.close();
        if (closed) return;
        setReconnecting(true);
        void apiClient
          .session()
          .then((session) => {
            if (!session.authenticated) {
              go("/login");
              return;
            }
            timer = window.setTimeout(connect, backoff);
            backoff = Math.min(backoff * 2, 8000);
          })
          .catch((err) => {
            if (err instanceof ApiError && err.status === 401) {
              go("/login");
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
    };
  }, [runKey]);

  useEffect(() => {
    const pre = preRef.current;
    if (!pre) return;
    const nearBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
    if (pinned || nearBottom) {
      pre.scrollTop = pre.scrollHeight;
      setPinned(true);
    }
  }, [lines, pinned]);

  const jump = () => {
    const pre = preRef.current;
    if (!pre) return;
    pre.scrollTop = pre.scrollHeight;
    setPinned(true);
  };

  return (
    <section class="card log-card">
      <div class="log-header">
        <strong>Output</strong>
        <div style={{ display: "flex", gap: "12px", alignItems: "center" }}>
          <span class={`log-indicator ${!reconnecting ? "live" : ""}`}>
            <span class="log-dot" />
            {reconnecting ? "Reconnecting…" : "Live"}
          </span>
          {!pinned && (
            <button type="button" class="btn-secondary" onClick={jump}>
              Jump to latest
            </button>
          )}
        </div>
      </div>
      <pre
        ref={preRef}
        class="log-pre"
        onScroll={() => {
          const pre = preRef.current;
          if (!pre) return;
          const nearBottom =
            pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
          setPinned(nearBottom);
        }}
      >
        {lines.join("\n")}
      </pre>
    </section>
  );
}
