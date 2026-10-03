import { QueryClient, QueryClientProvider } from "@tanstack/preact-query";
import { cleanup, render, screen } from "@testing-library/preact";
import { afterEach, describe, expect, it } from "vitest";
import snapshots from "../../../tests/fixtures/job-contract/snapshots.json";
import type { JobSnapshot } from "../api";
import { JobProgress } from "./JobProgress";

afterEach(cleanup);

describe("JobProgress", () => {
  it("shows target, terminal status, partial outcomes, and bounded logs", () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobProgress job={snapshots.partial_failure as JobSnapshot} />
      </QueryClientProvider>,
    );

    expect(screen.getByText("Refresh failed")).toBeTruthy();
    expect(screen.getByText("2 targets · 1 failed")).toBeTruthy();
    expect(screen.getByText("dropout/sample")).toBeTruthy();
    expect(screen.getByText("source timeout")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("renders live stage, target, and logs for a running job", () => {
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobProgress job={snapshots.running as JobSnapshot} />
      </QueryClientProvider>,
    );

    expect(screen.getByText("discover · youtube|sample · 0/1")).toBeTruthy();
    expect(screen.getByText("Fetching sample")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy();
  });
});
