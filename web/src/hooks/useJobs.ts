import { useQuery, useQueryClient } from "@tanstack/preact-query";
import { useEffect, useRef } from "preact/hooks";
import type { JobSnapshot } from "../api";
import { apiClient } from "../api";
import { queryKeys } from "../queryKeys";
import { useOnline, usePageVisible } from "./useOnline";

const TERMINAL = new Set(["succeeded", "failed", "cancelled", "interrupted"]);

export function nextJobPollInterval(state: {
  enabled: boolean;
  online: boolean;
  visible: boolean;
  active: boolean;
  hasMoreLogs: boolean;
}): number | false {
  return state.enabled && state.online && state.visible && (state.active || state.hasMoreLogs)
    ? 1000
    : false;
}

export function useJobs(poll = false) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const visible = usePageVisible();
  const session = useQuery({
    queryKey: queryKeys.session(),
    queryFn: () => apiClient.session(),
    staleTime: 30_000,
    retry: false,
  });
  return useQuery({
    queryKey: queryKeys.jobs(),
    queryFn: async () => {
      const previous = queryClient.getQueryData<JobsData>(queryKeys.jobs());
      const list = await apiClient.getJobs();
      const current = list.active ?? list.history[0] ?? null;
      const logsByJob = { ...(previous?.logsByJob ?? {}) };
      const historyById = new Map(list.history.map((job) => [job.id, job]));
      let active = list.active;
      const candidates = new Map<string, JobSnapshot>();
      if (list.active) candidates.set(list.active.id, list.active);
      if (current) candidates.set(current.id, current);
      for (const item of list.history) {
        if (logsByJob[item.id]?.hasMore) candidates.set(item.id, item);
      }
      for (const [id, candidate] of candidates) {
        const prior = logsByJob[id];
        const after = prior?.snapshot.log_cursor ?? 0;
        const snapshot = await apiClient.getJob(id, after);
        const listed = candidate.logs ?? [];
        const old = prior?.snapshot.logs ?? [];
        const byNumber = new Map(
          [...listed, ...old, ...snapshot.logs].map((line) => [line.n, line]),
        );
        const merged = {
          ...snapshot,
          logs: [...byNumber.values()].sort((a, b) => a.n - b.n).slice(-1000),
        };
        logsByJob[id] = { snapshot: merged, hasMore: snapshot.logs.length === 200 };
        if (active?.id === id) active = merged;
        if (historyById.has(id)) historyById.set(id, merged);
      }
      const history = [...historyById.values()];
      const retainedIds = new Set(history.map((job) => job.id));
      if (active) retainedIds.add(active.id);
      for (const id of Object.keys(logsByJob)) {
        if (!retainedIds.has(id)) delete logsByJob[id];
      }
      const focused = active ?? history[0] ?? null;
      const hasMoreLogs = Object.values(logsByJob).some((entry) => entry.hasMore);
      return { ...list, active, history, focused, hasMoreLogs, logsByJob };
    },
    refetchInterval: (query) => {
      const data = query.state.data as
        | { active?: JobSnapshot | null; hasMoreLogs?: boolean }
        | undefined;
      return nextJobPollInterval({
        enabled: poll,
        online,
        visible,
        active: Boolean(data?.active),
        hasMoreLogs: Boolean(data?.hasMoreLogs),
      });
    },
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
    enabled: session.data?.authenticated === true,
  });
}

export function JobLifecycle() {
  const queryClient = useQueryClient();
  const jobs = useJobs(true);
  const invalidated = useRef(new Set<string>());
  const observedActive = useRef(new Set<string>());
  useEffect(() => {
    const snapshots = [jobs.data?.active, ...(jobs.data?.history ?? [])].filter(
      (job, index, all): job is JobSnapshot =>
        Boolean(job && all.findIndex((row) => row?.id === job.id) === index),
    );
    for (const job of snapshots) {
      if (["queued", "running", "stopping"].includes(job.status)) {
        observedActive.current.add(job.id);
        continue;
      }
      if (
        !TERMINAL.has(job.status) ||
        !observedActive.current.has(job.id) ||
        invalidated.current.has(job.id)
      )
        continue;
      invalidated.current.add(job.id);
      void queryClient.invalidateQueries({ queryKey: queryKeys.queue() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.seriesList() });
      const result = job.result as { results?: { platform?: string; slug?: string }[] } | null;
      for (const target of result?.results ?? []) {
        if (target.platform && target.slug) {
          void queryClient.invalidateQueries({
            queryKey: queryKeys.series(target.platform, target.slug),
          });
          void queryClient.invalidateQueries({
            queryKey: queryKeys.disk(target.platform, target.slug),
          });
          void queryClient.invalidateQueries({
            queryKey: queryKeys.episodesSeries(target.platform, target.slug),
          });
          void queryClient.invalidateQueries({
            queryKey: queryKeys.missing(target.platform, target.slug),
          });
        }
      }
    }
  }, [jobs.dataUpdatedAt, queryClient]);
  return null;
}

type JobsData = {
  active: JobSnapshot | null;
  history: JobSnapshot[];
  focused: JobSnapshot | null;
  total: number;
  hasMoreLogs: boolean;
  logsByJob: Record<string, { snapshot: JobSnapshot; hasMore: boolean }>;
};
