import { describe, expect, it } from "vitest";
import { ansiStyleClass, hasAnsiStyle, parseAnsi } from "./ansiColor";

describe("parseAnsi", () => {
  it("parses basic foreground colors", () => {
    const spans = parseAnsi("\x1b[32mok\x1b[0m");
    expect(spans).toEqual([{ text: "ok", style: { fg: "green" } }]);
  });

  it("parses combined sgr codes", () => {
    const spans = parseAnsi("\x1b[0;32m12\x1b[0m of \x1b[0;32m121\x1b[0m");
    expect(spans.map((span) => span.text).join("")).toBe("12 of 121");
    expect(spans[0]?.style.fg).toBe("green");
    expect(spans[2]?.style.fg).toBe("green");
  });

  it("parses bold, dim, and yellow", () => {
    const spans = parseAnsi("\x1b[1mDone\x1b[0m  \x1b[2mdry-run\x1b[0m  \x1b[33mwarn\x1b[0m");
    expect(spans[0]).toEqual({ text: "Done", style: { bold: true } });
    expect(spans[1]).toEqual({ text: "  ", style: {} });
    expect(spans[2]).toEqual({ text: "dry-run", style: { dim: true } });
    expect(spans[4]).toEqual({ text: "warn", style: { fg: "yellow" } });
  });

  it("round-trips plain text", () => {
    const src = "hello\nworld";
    expect(
      parseAnsi(src)
        .map((span) => span.text)
        .join(""),
    ).toBe(src);
  });
});

describe("ansiStyleClass", () => {
  it("maps styles to css classes", () => {
    expect(ansiStyleClass({ bold: true, fg: "red" })).toBe("ansi-bold ansi-red");
    expect(hasAnsiStyle({})).toBe(false);
    expect(hasAnsiStyle({ dim: true })).toBe(true);
  });
});
