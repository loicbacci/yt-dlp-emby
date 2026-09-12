import { afterEach, describe, expect, it } from "vitest";
import { go, setNavigator } from "./nav";

describe("go", () => {
  afterEach(() => {
    setNavigator(null);
  });

  it("queues until a navigator is registered instead of reloading", () => {
    const seen: string[] = [];
    go("/setup");
    setNavigator((url) => {
      seen.push(url);
    });
    expect(seen).toEqual(["/setup"]);
  });

  it("navigates immediately when a navigator exists", () => {
    const seen: string[] = [];
    setNavigator((url) => {
      seen.push(url);
    });
    go("/login");
    expect(seen).toEqual(["/login"]);
  });
});
