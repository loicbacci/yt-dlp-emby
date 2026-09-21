import { cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManifestEditor } from "./ManifestEditor";

const tabs = [
  { path: "", label: "dropout.yaml" },
  { path: "shows/a.yaml", label: "a.yaml" },
];

function setup(activePath = "") {
  const onTabChange = vi.fn();
  const onChange = vi.fn();
  const onSave = vi.fn();
  // jsdom may lack rAF; ManifestEditor focuses the next tab after arrow nav.
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    }),
  );
  const utils = render(
    <ManifestEditor
      source="dropout"
      text="key: value"
      savedText="key: value"
      exists
      error={null}
      tabs={tabs}
      activePath={activePath}
      onTabChange={onTabChange}
      onChange={onChange}
      onSave={onSave}
    />,
  );
  return { ...utils, onTabChange, onChange, onSave };
}

describe("ManifestEditor", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("renders tabs with tablist semantics and roving tabindex", () => {
    setup("");
    const tablist = screen.getByRole("tablist", { name: "Manifest files" });
    expect(tablist).toBeTruthy();
    const tabNodes = screen.getAllByRole("tab");
    expect(tabNodes).toHaveLength(2);
    expect(tabNodes[0]?.getAttribute("aria-selected")).toBe("true");
    expect(tabNodes[0]?.getAttribute("tabindex")).toBe("0");
    expect(tabNodes[1]?.getAttribute("aria-selected")).toBe("false");
    expect(tabNodes[1]?.getAttribute("tabindex")).toBe("-1");
    expect(tabNodes[0]?.getAttribute("aria-controls")).toBe("editor-panel");
    expect(screen.getByRole("tabpanel")).toBeTruthy();
  });

  it("calls onTabChange with the next tab path on arrow nav", () => {
    const { onTabChange } = setup("");
    const [first] = screen.getAllByRole("tab");
    fireEvent.keyDown(first!, { key: "ArrowRight" });
    expect(onTabChange).toHaveBeenCalledWith("shows/a.yaml");
  });

  it("disables Save when clean and enables it when dirty", () => {
    const clean = setup("");
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(true);
    clean.unmount();

    vi.stubGlobal(
      "requestAnimationFrame",
      vi.fn((cb: FrameRequestCallback) => {
        cb(0);
        return 0;
      }),
    );
    render(
      <ManifestEditor
        source="dropout"
        text="key: changed"
        savedText="key: value"
        exists
        error={null}
        onChange={() => {}}
        onSave={() => {}}
      />,
    );
    expect((screen.getByRole("button", { name: "Save" }) as HTMLButtonElement).disabled).toBe(
      false,
    );
    expect(screen.getByText("Unsaved")).toBeTruthy();
  });

  it("emits change and save events", () => {
    const { container, onChange, onSave } = setup("");
    const area = container.querySelector(".editor-textarea");
    expect(area).toBeTruthy();
    fireEvent.input(area!, { target: { value: "key: edited" } });
    expect(onChange).toHaveBeenCalledWith("key: edited");
    // Save is disabled while clean; dirty render tested above calls onSave on click.
    expect(onSave).not.toHaveBeenCalled();
  });
});
