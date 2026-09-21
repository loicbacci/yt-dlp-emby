import { useQuery } from "@tanstack/preact-query";
import { ApiError, type Run, apiClient } from "./api";
import { isBrowserOnline, isPageVisible } from "./hooks/useOnline";
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

function useAuthenticated(): boolean {
  const session = useSession();
  return session.data?.authenticated === true;
}

export function useAppRun() {
  const enabled = useAuthenticated();
  return useQuery({
    queryKey: queryKeys.run(),
    queryFn: () => apiClient.getRun(),
    enabled,
    refetchInterval: (query) => {
      if (!isBrowserOnline() || !isPageVisible()) return false;
      return query.state.data?.status === "running" ? 2000 : 10_000;
    },
    refetchIntervalInBackground: false,
    staleTime: 1000,
  });
}

export function usePlan() {
  const enabled = useAuthenticated();
  return useQuery({
    queryKey: queryKeys.plan(),
    queryFn: async () => {
      try {
        return await apiClient.getPlan();
      } catch (err) {
        if (err instanceof ApiError && err.status === 404) return null;
        throw err;
      }
    },
    enabled,
    staleTime: 5_000,
    refetchInterval: () => (isBrowserOnline() && isPageVisible() ? 10_000 : false),
    refetchIntervalInBackground: false,
  });
}
