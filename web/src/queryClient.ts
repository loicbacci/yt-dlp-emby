import { MutationCache, QueryCache, QueryClient } from "@tanstack/preact-query";
import { type Session, UnauthorizedError } from "./api";
import { go } from "./nav";
import { queryKeys } from "./queryKeys";

export const EPISODE_STALE_MS = 12 * 60 * 60 * 1000;
export const DISK_STALE_MS = 30 * 1000;

function redirectIfUnauthorized(error: unknown): void {
  if (!(error instanceof UnauthorizedError)) return;
  // Stop authed polling immediately, before navigation completes.
  const prev = queryClient.getQueryData<Session>(queryKeys.session());
  queryClient.setQueryData<Session>(queryKeys.session(), {
    setup_required: prev?.setup_required ?? false,
    authenticated: false,
  });
  go("/login");
}

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: redirectIfUnauthorized,
    }),
    mutationCache: new MutationCache({
      onError: redirectIfUnauthorized,
    }),
    defaultOptions: {
      queries: {
        gcTime: 24 * 60 * 60 * 1000,
        // Never retry 401s: a second identical request can't succeed and
        // doubles log noise on expiry races.
        retry: (failureCount, error) => !(error instanceof UnauthorizedError) && failureCount < 1,
        refetchOnWindowFocus: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}

export const queryClient = createAppQueryClient();
