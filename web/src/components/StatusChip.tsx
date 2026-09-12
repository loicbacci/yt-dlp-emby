import type { Run } from "../api";

function labelFor(run: Run): string {
  if (run.status === "idle") return "Idle";
  if (run.status === "running") return "Running";
  if (run.status === "stopping") return "Stopping";
  if (run.exit_code === 0) return "Done";
  if (run.exit_code === 130) return "Stopped";
  return "Failed";
}

function classFor(run: Run): string {
  if (run.status === "running") return "status-running";
  if (run.status === "stopping") return "status-stopping";
  if (run.status === "exited" && run.exit_code === 0) return "status-done";
  if (run.status === "exited" && run.exit_code === 130) return "status-stopped";
  if (run.status === "exited") return "status-failed";
  return "";
}

export function StatusChip({ run }: { run: Run }) {
  return (
    <span class={`status-chip ${classFor(run)}`}>
      <span class="status-dot" />
      {labelFor(run)}
    </span>
  );
}
