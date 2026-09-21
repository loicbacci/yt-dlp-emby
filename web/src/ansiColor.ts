export type AnsiStyle = {
  bold?: boolean;
  dim?: boolean;
  fg?: "red" | "green" | "yellow";
};

export type AnsiSpan = { text: string; style: AnsiStyle };

const ANSI_RE = /\x1b\[([0-9;]*)m/g;

function resetStyle(): AnsiStyle {
  return {};
}

function applyCode(style: AnsiStyle, code: number): AnsiStyle {
  switch (code) {
    case 0:
      return resetStyle();
    case 1:
      return { ...style, bold: true };
    case 2:
      return { ...style, dim: true };
    case 22:
      return { ...style, bold: false };
    case 31:
      return { ...style, fg: "red" };
    case 32:
      return { ...style, fg: "green" };
    case 33:
      return { ...style, fg: "yellow" };
    case 39:
      return { ...style, fg: undefined };
    default:
      return style;
  }
}

function applySgr(style: AnsiStyle, body: string): AnsiStyle {
  if (!body) {
    return resetStyle();
  }
  let next = style;
  for (const part of body.split(";")) {
    const code = Number(part);
    if (!Number.isNaN(code)) {
      next = applyCode(next, code);
    }
  }
  return next;
}

function pushSpan(out: AnsiSpan[], text: string, style: AnsiStyle): void {
  if (!text) {
    return;
  }
  const last = out[out.length - 1];
  if (
    last &&
    last.style.bold === style.bold &&
    last.style.dim === style.dim &&
    last.style.fg === style.fg
  ) {
    last.text += text;
    return;
  }
  out.push({ text, style: { ...style } });
}

export function parseAnsi(text: string): AnsiSpan[] {
  const out: AnsiSpan[] = [];
  let style: AnsiStyle = resetStyle();
  let index = 0;
  ANSI_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = ANSI_RE.exec(text)) !== null) {
    pushSpan(out, text.slice(index, match.index), style);
    style = applySgr(style, match[1] ?? "");
    index = match.index + match[0].length;
  }
  pushSpan(out, text.slice(index), style);
  return out.length ? out : [{ text, style: resetStyle() }];
}

export function ansiStyleClass(style: AnsiStyle): string {
  const classes: string[] = [];
  if (style.bold) {
    classes.push("ansi-bold");
  }
  if (style.dim) {
    classes.push("ansi-dim");
  }
  if (style.fg) {
    classes.push(`ansi-${style.fg}`);
  }
  return classes.join(" ");
}

export function hasAnsiStyle(style: AnsiStyle): boolean {
  return Boolean(style.bold || style.dim || style.fg);
}
