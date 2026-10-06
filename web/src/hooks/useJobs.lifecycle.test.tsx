import { QueryClient, QueryClientProvider } from "@tanstack/preact-query";
import { cleanup, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import snapshots from "../../../tests/fixtures/job-contract/snapshots.json";
import { type JobSnapshot, apiClient } from "../api";
import { queryKeys } from "../queryKeys";
import { JobLifecycle, useJobs } from "./useJobs";

function Probe() {
  const query = useJobs();
  return <output data-testid="job-state">{query.data?.focused?.status ?? "loading"}</output>;
}

function wrap(client: QueryClient, probe = true) {
  return (
    <QueryClientProvider client={client}>
      <JobLifecycle />
      {probe && <Probe />}
    </QueryClientProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("JobLifecycle polling", () => {
  it("discovers an active job on load, survives page navigation, drains final log pages, and invalidates once", async () => {
    const running = snapshots.running as JobSnapshot;
    const terminal: JobSnapshot = {
      ...(snapshots.succeeded as JobSnapshot),
      id: running.id,
      result: { ok: true, results: [] },
    };
    const firstPage = Array.from({ length: 200 }, (_, index) => ({
      n: index + 2,
      ts: "2026-10-04T10:00:02+00:00",
      line: `line ${index + 2}`,
    }));
    const lastPage = Array.from({ length: 50 }, (_, index) => ({
      n: index + 202,
      ts: "2026-10-04T10:00:03+00:00",
      line: `line ${index + 202}`,
    }));
    vi.spyOn(apiClient, "session").mockResolvedValue({
      setup_required: false,
      authenticated: true,
    });
    const getJobs = vi
      .spyOn(apiClient, "getJobs")
      .mockResolvedValueOnce({ active: running, history: [], total: 1 })
      .mockResolvedValue({ active: null, history: [terminal], total: 1 });
    const getJob = vi
      .spyOn(apiClient, "getJob")
      .mockResolvedValueOnce({ ...running, logs: [running.logs[0]!], log_cursor: 1 })
      .mockResolvedValueOnce({ ...terminal, logs: firstPage, log_cursor: 201 })
      .mockResolvedValue({ ...terminal, logs: lastPage, log_cursor: 251 });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    const view = render(wrap(client));

    await waitFor(() => expect(screen.getByTestId("job-state").textContent).toBe("running"));
    expect(getJobs).toHaveBeenCalledTimes(1);
    expect(getJob).toHaveBeenLastCalledWith(running.id, 0);

    // The app-level lifecycle remains mounted while the route content changes.
    view.rerender(wrap(client, false));
    await waitFor(() => expect(getJob).toHaveBeenCalledTimes(3), { timeout: 3500 });
    view.rerender(wrap(client));
    await waitFor(() => expect(screen.getByTestId("job-state").textContent).toBe("succeeded"));
    expect(getJob.mock.calls.map((call) => call[1])).toEqual([0, 1, 201, 251]);
    expect(
      client.getQueryData<{ focused: JobSnapshot }>(queryKeys.jobs())?.focused.logs,
    ).toHaveLength(251);
    expect(
      invalidate.mock.calls.filter(([filters]) => filters?.queryKey?.[0] === "queue"),
    ).toHaveLength(1);
  });

  it("keeps a running job running when a snapshot request has a transport error", async () => {
    const running = snapshots.running as JobSnapshot;
    vi.spyOn(apiClient, "session").mockResolvedValue({
      setup_required: false,
      authenticated: true,
    });
    vi.spyOn(apiClient, "getJobs").mockResolvedValue({ active: running, history: [], total: 1 });
    vi.spyOn(apiClient, "getJob")
      .mockResolvedValueOnce(running)
      .mockRejectedValue(new TypeError("offline"));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(wrap(client));

    await waitFor(() => expect(screen.getByTestId("job-state").textContent).toBe("running"));
    await waitFor(() => expect(client.getQueryState(queryKeys.jobs())?.status).toBe("error"), {
      timeout: 2500,
    });
    expect(client.getQueryState(queryKeys.jobs())?.status).toBe("error");
    expect(client.getQueryData<{ active: JobSnapshot }>(queryKeys.jobs())?.active.status).toBe(
      "running",
    );
  });
});
