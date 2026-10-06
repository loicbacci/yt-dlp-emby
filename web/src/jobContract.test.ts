import { afterEach, describe, expect, it, vi } from "vitest";
import requests from "../../tests/fixtures/job-contract/requests.json";
import snapshots from "../../tests/fixtures/job-contract/snapshots.json";
import { apiClient, refreshJobRequest } from "./api";
import {
  jobSnapshotSchema,
  jobStartSchema,
  jobsListSchema,
  librarySnapshotSchema,
  planFileSchema,
} from "./types";

describe("shared job contract fixtures", () => {
  it("validates every shared lifecycle snapshot", () => {
    for (const key of [
      "queued",
      "running",
      "succeeded",
      "partial_failure",
      "cancelled",
      "interrupted",
    ] as const) {
      expect(jobSnapshotSchema.safeParse(snapshots[key]), key).toMatchObject({ success: true });
    }
  });

  it("validates stale plan and unavailable library without turning unknown counts into zero", () => {
    expect(planFileSchema.safeParse(snapshots.stale_plan).success).toBe(true);
    const library = librarySnapshotSchema.parse(snapshots.unavailable_library);
    expect(library.status).toBe("unavailable");
    expect(library.episodes).toBeNull();
    expect(library.series_exists).toBeNull();
  });

  it("validates the jobs list and the 202 start response", () => {
    expect(jobsListSchema.safeParse(requests.jobs).success).toBe(true);
    expect(jobStartSchema.safeParse(requests.refresh_start).success).toBe(true);
  });

  it("normalizes object-form worker targets to the display contract", () => {
    const job = jobSnapshotSchema.parse({
      ...snapshots.running,
      progress: {
        stage: "refresh",
        target: { platform: "dropout", slug: "sample" },
        completed: 0,
        total: 1,
      },
    });
    expect(job.progress?.target).toBe("dropout|sample");
  });
});

describe("job start transport", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("sends the discriminated refresh body and accepts only a 202 queued response", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        kind: "refresh",
        items: [{ platform: "youtube", slug: "sample" }],
      });
      return new Response(JSON.stringify(requests.refresh_start), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      apiClient.startJob({ kind: "refresh", items: [{ platform: "youtube", slug: "sample" }] }),
    ).resolves.toEqual(requests.refresh_start);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("uses a target config revision for scoped refresh and omits aggregate revisions", () => {
    const items = [{ platform: "dropout" as const, slug: "sample" }];
    expect(refreshJobRequest(items, "target-config-revision")).toEqual({
      kind: "refresh",
      items,
      expected_revision: "target-config-revision",
    });
    expect(refreshJobRequest(items)).toEqual({ kind: "refresh", items });
  });

  it("rejects a synchronous 200 response instead of treating it as completed work", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ results: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
      ),
    );
    await expect(
      apiClient.startJob({ kind: "refresh", items: [{ platform: "youtube", slug: "sample" }] }),
    ).rejects.toMatchObject({ status: 200, message: "Expected HTTP 202, received 200" });
  });
});
