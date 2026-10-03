import { useQuery } from "@tanstack/preact-query";
import { ApiError, type Run, apiClient } from "./api";
import { useJobs } from "./hooks/useJobs";
import { queryKeys } from "./queryKeys";

export const idleRun: Run = {
  status: "idle",
  phase: "idle",
  source: null,
  dry_run: false,
  verbose: false,
  force: false,
  started_at: null,
  finished_at: null,
  exit_code: null,
  plan: null,
};

export function useSession() {
  return useQuery({
    queryKey: queryKeys.session(),
    queryFn: () => apiClient.session(),
    staleTime: 30_000,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useAppRun() {
  const jobs = useJobs();
  const job = jobs.data?.active ?? jobs.data?.focused;
  const active = Boolean(job && ["queued", "running", "stopping"].includes(job.status));
  const data: Run | undefined = job
    ? {
        status: job.status === "stopping" ? "stopping" : active ? "running" : "exited",
        phase:
          active && job.kind === "refresh"
            ? "planning"
            : active && job.kind === "download"
              ? "downloading"
              : job.status === "stopping"
                ? "stopping"
                : "exited",
        source: null,
        dry_run: false,
        verbose: false,
        force: false,
        started_at: job.started_at ?? job.created_at,
        finished_at: job.finished_at,
        exit_code:
          job.status === "succeeded"
            ? 0
            : job.status === "cancelled"
              ? 130
              : job.status === "failed" || job.status === "interrupted"
                ? 1
                : null,
        plan: null,
        progress: null,
      }
    : undefined;
  return { ...jobs, data, isPending: jobs.isPending };
}

export function usePlan(force = false, create = false) {
  const enabled = useSession().data?.authenticated === true;
  return useQuery({
    queryKey: queryKeys.plan(force, create),
    queryFn: async () => {
      try {
        return await apiClient.getPlan(force, create);
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    enabled,
    staleTime: 5_000,
  });
}
