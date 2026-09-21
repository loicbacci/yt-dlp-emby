import { describe, expect, it } from "vitest";
import { highlightYaml } from "./yamlHighlight";

function kinds(source: string): string[] {
  return highlightYaml(source).map((token) => `${token.kind}:${token.text}`);
}

describe("highlightYaml", () => {
  it("marks keys, numbers, and comments", () => {
    expect(kinds("season: 1  # first")).toEqual([
      "key:season",
      "punct::",
      "text: ",
      "number:1",
      "text:  ",
      "comment:# first",
    ]);
  });

  it("marks quoted strings and list dashes", () => {
    expect(kinds('  - title: "Hello"')).toEqual([
      "text:  ",
      "punct:-",
      "text: ",
      "key:title",
      "punct::",
      "text: ",
      'string:"Hello"',
    ]);
  });

  it("marks booleans", () => {
    expect(kinds("ok: true")).toEqual(["key:ok", "punct::", "text: ", "bool:true"]);
  });

  it("round-trips source text", () => {
    const src = "library: /mnt/nas/video\n# comment\nseries:\n  - name: Example\n";
    expect(
      highlightYaml(src)
        .map((t) => t.text)
        .join(""),
    ).toBe(src);
  });
});
