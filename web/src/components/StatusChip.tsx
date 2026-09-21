import type { Run } from "../api";
import { listingLabel } from "../runQueue";

function labelFor(run: Run): string {
  if (run.phase === "planning") {
    return listingLabel(run.source);
  }
  if (run.phase === "downloading") {
    const src = run.source === "youtube" ? "YouTube" : run.source === "dropout" ? "Dropout" : "";
    return src ? `Downloading ${src}` : "Downloading";
  }
  if (run.status === "idle" || run.phase === "idle") return "Idle";
  if (run.status === "stopping" || run.phase === "stopping") return "Stopping";
  if (run.exit_code === 0) return "Done";
  if (run.exit_code === 130) return "Stopped";
  if (run.status === "exited") return "Failed";
  return "Running";
}

function classFor(run: Run): string {
  if (run.phase === "planning" || run.phase === "downloading" || run.status === "running") {
    return "status-running";
  }
  if (run.status === "stopping" || run.phase === "stopping") return "status-stopping";
  if (run.status === "exited" && run.exit_code === 0) return "status-done";
  if (run.status === "exited" && run.exit_code === 130) return "status-stopped";
  if (run.status === "exited") return "status-failed";
  return "";
}

export function StatusChip({ run, loading }: { run: Run; loading?: boolean }) {
  if (loading) {
    return (
      <span class="status-chip" role="status" aria-label="Loading run status">
        <span class="status-dot" />…
      </span>
    );
  }
  return (
    <span class={`status-chip ${classFor(run)}`}>
      <span class="status-dot" />
      {labelFor(run)}
    </span>
  );
}
