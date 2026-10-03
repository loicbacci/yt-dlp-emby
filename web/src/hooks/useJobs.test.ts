import { describe, expect, it } from "vitest";
import { nextJobPollInterval } from "./useJobs";

describe("shared job polling cadence", () => {
  const active = { enabled: true, online: true, visible: true, active: true, hasMoreLogs: false };

  it("polls active jobs once per second", () => {
    expect(nextJobPollInterval(active)).toBe(1000);
  });

  it("pauses offline and hidden tabs", () => {
    expect(nextJobPollInterval({ ...active, online: false })).toBe(false);
    expect(nextJobPollInterval({ ...active, visible: false })).toBe(false);
  });

  it("stops after terminal state unless another bounded log page remains", () => {
    expect(nextJobPollInterval({ ...active, active: false })).toBe(false);
    expect(nextJobPollInterval({ ...active, active: false, hasMoreLogs: true })).toBe(1000);
  });

  it("does not poll before authentication enables the observer", () => {
    expect(nextJobPollInterval({ ...active, enabled: false })).toBe(false);
  });
});
