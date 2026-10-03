import { useState } from "preact/hooks";
import { type ProgressState, emptyProgress } from "../runQueue";
import type { QueueTree } from "../runQueue";

// Kept as a view adapter for the existing queue tree while job progress and
// bounded logs are rendered by JobProgress. No event stream is opened here.
export function useRunEvents(_runKey: string, _treeRef: { current: QueueTree }, _online: boolean) {
  const [progress, setProgress] = useState<ProgressState>(emptyProgress());
  const [listingSeries, setListingSeries] = useState<string | null>(null);
  return { progress, setProgress, listingSeries, setListingSeries, eventsReconnecting: false };
}
