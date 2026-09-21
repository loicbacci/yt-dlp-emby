export type YamlKind = "text" | "comment" | "key" | "punct" | "string" | "number" | "bool";

export type YamlToken = { kind: YamlKind; text: string };

const KEY = /^[A-Za-z_][\w.-]*/;
const BOOL = /^(?:true|false|null|True|False|Null|TRUE|FALSE|NULL|yes|no|on|off)\b/;
const NUM = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/;

function isValueBoundary(ch: string | undefined): boolean {
  return ch === undefined || /[\s,[\]{}]/.test(ch);
}

function tokenizeValue(s: string): YamlToken[] {
  const out: YamlToken[] = [];
  let i = 0;
  while (i < s.length) {
    const ch = s[i];
    if (ch === undefined) break;
    if (ch === "#") {
      out.push({ kind: "comment", text: s.slice(i) });
      break;
    }
    if (ch === '"' || ch === "'") {
      let j = i + 1;
      while (j < s.length) {
        if (s[j] === "\\" && ch === '"') {
          j += 2;
          continue;
        }
        if (s[j] === ch) {
          j += 1;
          break;
        }
        j += 1;
      }
      out.push({ kind: "string", text: s.slice(i, j) });
      i = j;
      continue;
    }
    const rest = s.slice(i);
    const boolMatch = BOOL.exec(rest);
    if (boolMatch && isValueBoundary(s[i - 1])) {
      out.push({ kind: "bool", text: boolMatch[0] });
      i += boolMatch[0].length;
      continue;
    }
    const numMatch = NUM.exec(rest);
    if (numMatch && isValueBoundary(s[i - 1])) {
      const next = s[i + numMatch[0].length];
      if (next === undefined || /[\s,#\]},]/.test(next)) {
        out.push({ kind: "number", text: numMatch[0] });
        i += numMatch[0].length;
        continue;
      }
    }
    out.push({ kind: "text", text: ch });
    i += 1;
  }
  return mergeText(out);
}

function mergeText(tokens: YamlToken[]): YamlToken[] {
  const out: YamlToken[] = [];
  for (const token of tokens) {
    const last = out[out.length - 1];
    if (last && last.kind === token.kind) {
      last.text += token.text;
    } else {
      out.push({ ...token });
    }
  }
  return out;
}

function tokenizeLine(line: string): YamlToken[] {
  if (line.trimStart().startsWith("#")) {
    return [{ kind: "comment", text: line }];
  }
  const tokens: YamlToken[] = [];
  let i = 0;
  while (i < line.length && (line[i] === " " || line[i] === "\t")) {
    i += 1;
  }
  if (i > 0) {
    tokens.push({ kind: "text", text: line.slice(0, i) });
  }
  if (line[i] === "-" && (line[i + 1] === " " || line[i + 1] === "\t" || i + 1 === line.length)) {
    tokens.push({ kind: "punct", text: "-" });
    i += 1;
    const start = i;
    while (i < line.length && (line[i] === " " || line[i] === "\t")) {
      i += 1;
    }
    if (i > start) {
      tokens.push({ kind: "text", text: line.slice(start, i) });
    }
  }
  const keyMatch = KEY.exec(line.slice(i));
  if (keyMatch && line[i + keyMatch[0].length] === ":") {
    tokens.push({ kind: "key", text: keyMatch[0] });
    tokens.push({ kind: "punct", text: ":" });
    i += keyMatch[0].length + 1;
  }
  tokens.push(...tokenizeValue(line.slice(i)));
  return mergeText(tokens);
}

export function highlightYaml(source: string): YamlToken[] {
  if (!source) {
    return [];
  }
  const parts = source.split("\n");
  const tokens: YamlToken[] = [];
  parts.forEach((line, index) => {
    tokens.push(...tokenizeLine(line));
    if (index < parts.length - 1) {
      tokens.push({ kind: "text", text: "\n" });
    }
  });
  return mergeText(tokens);
}
