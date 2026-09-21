import { Fragment } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { ansiStyleClass, hasAnsiStyle, parseAnsi } from "../ansiColor";
import { ApiError, apiClient } from "../api";
import { go } from "../nav";
import { pushToast } from "./Toast";

type ParsedLine = { id: number; spans: ReturnType<typeof parseAnsi> };

function AnsiLine({ spans }: { spans: ParsedLine["spans"] }) {
  return (
    <>
      {spans.map((span, index) =>
        hasAnsiStyle(span.style) ? (
          <span key={index} class={ansiStyleClass(span.style)}>
            {span.text}
          </span>
        ) : (
          <Fragment key={index}>{span.text}</Fragment>
        ),
      )}
    </>
  );
}

const COMPACT_MAX_LINES = 500;
const MAX_LINES = 2000;

export function LogViewer({
  runKey,
  compact = false,
}: {
  runKey: string;
  compact?: boolean;
}) {
  const preRef = useRef<HTMLPreElement>(null);
  const lastNRef = useRef(0);
  const nextId = useRef(1);
  const [lines, setLines] = useState<ParsedLine[]>([]);
  const [reconnecting, setReconnecting] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);

  useEffect(() => {
    setLines([]);
    lastNRef.current = 0;
    nextId.current = 1;
  }, [runKey]);

  useEffect(() => {
    let source: EventSource | null = null;
    let backoff = 1000;
    let closed = false;
    let timer: number | undefined;
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
      setReconnecting(lastNRef.current > 0);
      source = new EventSource(`/api/runs/log?after=${lastNRef.current}`);
      source.onmessage = (event) => {
        setReconnecting(false);
        backoff = 1000;
        try {
          const payload = JSON.parse(event.data) as { n: number; line: string };
          lastNRef.current = payload.n;
          const parsed: ParsedLine = {
            id: nextId.current++,
            spans: parseAnsi(payload.line),
          };
          setLines((prev) => {
            const cap = compact ? COMPACT_MAX_LINES : MAX_LINES;
            const next = [...prev, parsed];
            return next.length > cap ? next.slice(-cap) : next;
          });
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
    };
  }, [runKey, compact]);

  useEffect(() => {
    if (!autoScroll) return;
    const pre = preRef.current;
    if (!pre) return;
    pre.scrollTop = pre.scrollHeight;
  }, [lines, autoScroll]);

  const jumpToLatest = () => {
    const pre = preRef.current;
    if (!pre) return;
    pre.scrollTop = pre.scrollHeight;
    setAutoScroll(true);
  };

  const cap = compact ? COMPACT_MAX_LINES : MAX_LINES;
  const trimmed = lines.length >= cap ? `Showing last ${cap} lines` : null;

  return (
    <section class={`card log-card${compact ? " log-card--compact" : ""}`}>
      <div class="log-header">
        <strong>{compact ? "Technical log" : "Output"}</strong>
        <div class="log-header-actions">
          <label class="log-autoscroll">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => {
                const on = (e.target as HTMLInputElement).checked;
                setAutoScroll(on);
                if (on) jumpToLatest();
              }}
            />
            Auto-scroll
          </label>
          <span class={`log-indicator ${!reconnecting ? "live" : ""}`}>
            <span class="log-dot" />
            {reconnecting ? "Reconnecting…" : "Live"}
          </span>
          {!autoScroll && (
            <button type="button" class="btn-secondary btn-compact" onClick={jumpToLatest}>
              Latest
            </button>
          )}
        </div>
      </div>
      {trimmed && <p class="log-trim-hint">{trimmed}</p>}
      <pre
        ref={preRef}
        class={`log-pre${compact ? " log-pre--compact" : ""}`}
        onScroll={() => {
          const pre = preRef.current;
          if (!pre) return;
          const nearBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 40;
          if (!nearBottom && autoScroll) setAutoScroll(false);
        }}
      >
        {lines.length === 0 ? (
          <span class="run-hint">No output yet</span>
        ) : (
          lines.map((line, index) => (
            <Fragment key={line.id}>
              {index > 0 ? "\n" : null}
              <AnsiLine spans={line.spans} />
            </Fragment>
          ))
        )}
      </pre>
    </section>
  );
}
