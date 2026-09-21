import { useEffect, useRef } from "preact/hooks";
import type { Source } from "../api";
import { yamlLooksBroken } from "../formValidation";
import { moveRovingIndex } from "../hooks/useRoving";
import { highlightYaml } from "../yamlHighlight";

export type EditorTab = { path: string; label: string };

export function ManifestEditor({
  source,
  text,
  savedText,
  exists,
  error,
  notices,
  tabs,
  activePath,
  onTabChange,
  onChange,
  onSave,
}: {
  source: Source;
  text: string;
  savedText: string;
  exists: boolean;
  error: string | null;
  notices?: string[];
  tabs?: EditorTab[];
  activePath?: string;
  onTabChange?: (path: string) => void;
  onChange: (text: string) => void;
  onSave: () => void;
}) {
  const dirty = text !== savedText;
  // Live client-side syntax hint while editing. Non-blocking: the server is
  // the source of truth and validates again on save (root) / write (imports).
  const liveYamlError = dirty ? yamlLooksBroken(text) : null;
  const filename =
    activePath && activePath.length > 0
      ? activePath
      : source === "youtube"
        ? "youtube.yaml"
        : "dropout.yaml";
  const preRef = useRef<HTMLPreElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const showTabs = Boolean(tabs && tabs.length > 1 && onTabChange);
  const activeIndex = tabs?.findIndex((tab) => tab.path === (activePath ?? "")) ?? -1;

  useEffect(() => {
    const pre = preRef.current;
    const area = textRef.current;
    if (!pre || !area) return;
    pre.scrollTop = area.scrollTop;
    pre.scrollLeft = area.scrollLeft;
  }, [text]);

  const syncScroll = () => {
    const pre = preRef.current;
    const area = textRef.current;
    if (!pre || !area) return;
    pre.scrollTop = area.scrollTop;
    pre.scrollLeft = area.scrollLeft;
  };

  return (
    <section class="card">
      {!exists && (
        <div class="banner">
          File not on disk yet. Save to create it. Start is disabled until then.
        </div>
      )}
      {notices?.map((notice) => (
        <div key={notice} class={notice.includes("is not set") ? "banner banner-warn" : "banner"}>
          {notice}
        </div>
      ))}
      {showTabs && (
        <div class="editor-tabs" role="tablist" aria-label="Manifest files">
          {tabs!.map((tab, index) => {
            const selected = tab.path === (activePath ?? "");
            const tabId = `editor-tab-${index}`;
            return (
              <button
                key={tab.path || "root"}
                ref={(el) => {
                  tabRefs.current[index] = el;
                }}
                type="button"
                role="tab"
                id={tabId}
                class={selected ? "editor-tab active" : "editor-tab"}
                aria-selected={selected}
                aria-controls="editor-panel"
                tabIndex={selected ? 0 : -1}
                onClick={() => onTabChange?.(tab.path)}
                onKeyDown={(e) => {
                  const next = moveRovingIndex(e as unknown as KeyboardEvent, tabs!.length, index);
                  if (next != null && tabs![next]) {
                    e.preventDefault();
                    onTabChange?.(tabs![next].path);
                    const focusNext = () => tabRefs.current[next]?.focus();
                    if (typeof requestAnimationFrame === "function") {
                      requestAnimationFrame(focusNext);
                    } else {
                      focusNext();
                    }
                  }
                }}
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      )}
      <div
        id="editor-panel"
        role={showTabs ? "tabpanel" : undefined}
        aria-labelledby={showTabs && activeIndex >= 0 ? `editor-tab-${activeIndex}` : undefined}
      >
        <div class="editor-header">
          <span class="editor-filename">{filename}</span>
          <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
            {dirty && <span class="editor-unsaved">Unsaved</span>}
            <button type="button" class="btn-secondary" disabled={!dirty} onClick={onSave}>
              Save
            </button>
          </div>
        </div>
        <div class="editor-frame">
          <pre ref={preRef} class="editor-highlight" aria-hidden="true">
            {highlightYaml(text).map((token, index) => (
              <span key={index} class={`tok-${token.kind}`}>
                {token.text}
              </span>
            ))}
          </pre>
          <textarea
            ref={textRef}
            class="editor-textarea"
            spellcheck={false}
            value={text}
            aria-label={filename}
            onScroll={syncScroll}
            onInput={(e) => {
              onChange((e.currentTarget as HTMLTextAreaElement).value);
            }}
          />
        </div>
        {liveYamlError && !error && (
          <div class="validation-error" role="status">
            {liveYamlError}
          </div>
        )}
        {error && (
          <div class="validation-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </section>
  );
}
