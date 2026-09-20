import { QueryClient } from "@tanstack/preact-query";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { shouldPersistQuery } from "./queryKeys";

export const EPISODE_STALE_MS = 12 * 60 * 60 * 1000;
export const DISK_STALE_MS = 30 * 1000;

export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: 24 * 60 * 60 * 1000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}

export const queryClient = createAppQueryClient();

export const queryPersister = createSyncStoragePersister({
  storage: typeof localStorage === "undefined" ? undefined : localStorage,
  key: "yt-dlp-emby-query",
  throttleTime: 1000,
});

export const persistQueryOptions = {
  persister: queryPersister,
  maxAge: 24 * 60 * 60 * 1000,
  buster: "2",
  dehydrateOptions: {
    shouldDehydrateQuery: (query: { state: { status: string }; queryKey: readonly unknown[] }) =>
      query.state.status === "success" && shouldPersistQuery(query.queryKey),
  },
};
