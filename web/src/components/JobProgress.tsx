import { useMutation, useQueryClient } from "@tanstack/preact-query";
import type { JobSnapshot } from "../api";
import { apiClient } from "../api";
import { queryKeys } from "../queryKeys";

type JobsData = {
  active: JobSnapshot | null;
  history: JobSnapshot[];
  total: number;
  focused: JobSnapshot | null;
  hasMoreLogs: boolean;
};
type JobOutcome = Record<string, unknown>;

function isOutcome(value: unknown): value is JobOutcome {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

const ACTIVE = new Set(["queued", "running", "stopping"]);

export function JobProgress({
  job,
  history = [],
}: { job: JobSnapshot | null; history?: JobSnapshot[] }) {
  const queryClient = useQueryClient();
  const cancel = useMutation({
    mutationFn: () => apiClient.cancelJob(job!.id),
    onSuccess: (snapshot) => {
      queryClient.setQueryData<JobsData>(queryKeys.jobs(), (data) =>
        data ? { ...data, active: snapshot, focused: snapshot } : data,
      );
    },
  });
  const retry = useMutation({
    mutationFn: (id: string) => apiClient.retryJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.jobs() }),
  });
  if (!job) return null;
  const active = ACTIVE.has(job.status);
  const progress = job.progress;
  const progressText = progress
    ? `${progress.stage}${progress.target ? ` · ${progress.target}` : ""}${progress.total != null ? ` · ${progress.completed}/${progress.total}` : ""}`
    : null;
  const elapsedFrom = job.started_at ?? job.created_at;
  const elapsed = Math.max(0, Math.floor((Date.now() - new Date(elapsedFrom).getTime()) / 1000));
  const result =
    job.result && typeof job.result === "object" ? (job.result as Record<string, unknown>) : null;
  const results = Array.isArray(result?.results) ? result.results.filter(isOutcome) : [];
  const errorText = (value: unknown): string | null => {
    if (typeof value === "string") return value;
    if (!value || typeof value !== "object") return null;
    const row = value as Record<string, unknown>;
    for (const key of ["error", "message", "detail"]) {
      if (typeof row[key] === "string") return row[key] as string;
    }
    return null;
  };
  return (
    <section
      class={`job-progress${active ? " is-active" : ""}`}
      aria-label="Background job"
      aria-live="polite"
    >
      <div class="job-progress-main">
        <div>
          <strong>
            {active
              ? `${job.kind[0]?.toUpperCase()}${job.kind.slice(1)} ${job.status}`
              : `${job.kind[0]?.toUpperCase()}${job.kind.slice(1)} ${job.status}`}
          </strong>
          {progressText && <span class="job-progress-stage">{progressText}</span>}
          <span class="job-progress-time">
            {active
              ? `${elapsed}s elapsed`
              : `Finished ${new Date(job.finished_at ?? job.created_at).toLocaleString()}`}
          </span>
          {errorText(job.error) && <span class="job-progress-error">{errorText(job.error)}</span>}
          {results.length > 0 && (
            <details class="job-results">
              <summary>
                {results.length} target{results.length === 1 ? "" : "s"} ·{" "}
                {results.filter((row) => Boolean(row.error)).length} failed
              </summary>
              <ul>
                {results.map((row, index) => (
                  <li key={`${row.platform ?? "target"}-${row.slug ?? index}`}>
                    <span>
                      {row.platform && row.slug
                        ? `${row.platform}/${row.slug}`
                        : `Target ${index + 1}`}
                    </span>
                    {row.error && (
                      <span class="job-progress-error">
                        {errorText(row.error) ?? "Target failed"}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
        <div class="job-progress-actions">
          {job.can_cancel && (
            <button
              class="btn-secondary"
              type="button"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              Stop
            </button>
          )}
          {job.can_retry && (
            <button
              class="btn-secondary"
              type="button"
              disabled={retry.isPending}
              onClick={() => retry.mutate(job.id)}
            >
              Retry
            </button>
          )}
        </div>
      </div>
      {job.logs.length > 0 && (
        <details class="job-log-details">
          <summary>
            Logs ({job.log_cursor}
            {job.logs_truncated ? ", earlier lines omitted" : ""})
          </summary>
          <pre aria-label="Job logs">{job.logs.map((line) => line.line).join("\n")}</pre>
        </details>
      )}
      {history.length > 1 && (
        <details class="job-history">
          <summary>Recent jobs ({history.length})</summary>
          <ul>
            {history.slice(1, 11).map((item) => (
              <li key={item.id}>
                <span>
                  {item.kind} · {item.status} · {new Date(item.created_at).toLocaleString()}
                </span>
                {item.can_retry && (
                  <button
                    type="button"
                    class="btn-ghost"
                    disabled={retry.isPending}
                    onClick={() => retry.mutate(item.id)}
                  >
                    Retry {item.kind}
                  </button>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
      {cancel.error instanceof Error && (
        <p class="job-progress-error" role="alert">
          {cancel.error.message}
        </p>
      )}
      {retry.error instanceof Error && (
        <p class="job-progress-error" role="alert">
          {retry.error.message}
        </p>
      )}
    </section>
  );
}
