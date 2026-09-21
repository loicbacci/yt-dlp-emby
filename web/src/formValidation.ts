export const DIGITS = /^\d+$/;
export const COOKIE_MAX_BYTES = 1_000_000;

export function parseNonNegInt(raw: string): number | null {
  const trimmed = raw.trim();
  if (!DIGITS.test(trimmed)) return null;
  return Number.parseInt(trimmed, 10);
}

export function parseOptionalInt(raw: string): { ok: true; value: number | null } | { ok: false } {
  const trimmed = raw.trim();
  if (trimmed === "") return { ok: true, value: null };
  const parsed = parseNonNegInt(trimmed);
  if (parsed == null) return { ok: false };
  return { ok: true, value: parsed };
}

export function isHttpUrl(raw: string): boolean {
  try {
    const parsed = new URL(raw.trim());
    return parsed.protocol === "http:" || parsed.protocol === "https:";
  } catch {
    return false;
  }
}

export function urlMatchesPlatform(raw: string, platform: "youtube" | "dropout"): boolean {
  try {
    const host = new URL(raw.trim()).hostname.toLowerCase();
    if (platform === "youtube") {
      return host.includes("youtube.com") || host === "youtu.be";
    }
    return host.includes("dropout.tv") || host.includes("vhx.tv");
  } catch {
    return false;
  }
}

export function pathHint(raw: string): string | null {
  const value = raw.trim();
  if (!value) return null;
  if (value.includes("..")) return "Paths should not contain ..";
  if (/^\/(proc|sys|dev)(\/|$)/.test(value)) return "Avoid system paths like /proc, /sys, /dev";
  if (!(value.startsWith("/") || value.startsWith("./") || !value.includes("/"))) {
    return "Use an absolute path or a data-relative path";
  }
  return null;
}

export function netscapeCookieError(text: string): string | null {
  if (new TextEncoder().encode(text).length > COOKIE_MAX_BYTES) {
    return "Cookie file must be 1MB or smaller";
  }
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/);
  const hasHeader = lines.some((line) => line.includes("Netscape HTTP Cookie File"));
  if (!hasHeader) {
    return "Expected a Netscape HTTP Cookie File header";
  }
  const rows = lines.filter((line) => line.trim() && !line.startsWith("#"));
  if (!rows.length) return "Paste at least one cookie row";
  if (!rows.some((line) => line.includes("\t"))) {
    return "Cookie rows should be tab-separated Netscape format";
  }
  return null;
}

export function yamlLooksBroken(text: string): string | null {
  const trimmed = text.trim();
  if (!trimmed) return "YAML is empty";
  if (trimmed.startsWith("{") && !trimmed.endsWith("}")) return "Unclosed JSON/YAML mapping";
  const open = (trimmed.match(/\[/g) ?? []).length;
  const close = (trimmed.match(/]/g) ?? []).length;
  if (open !== close) return "Unbalanced [ ] in YAML";
  return null;
}
