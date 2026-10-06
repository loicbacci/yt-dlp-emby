import { cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CreateSeriesModal } from "./CreateSeriesModal";

describe("CreateSeriesModal", () => {
  afterEach(cleanup);

  it("uses native required fields and keeps an invalid optional TVDB value actionable", () => {
    const onCreate = vi.fn(async () => {});
    render(<CreateSeriesModal existing={[]} onClose={vi.fn()} onCreate={onCreate} />);

    const title = screen.getByLabelText("Title *") as HTMLInputElement;
    const folder = screen.getByLabelText("Folder *") as HTMLInputElement;
    const tvdb = screen.getByLabelText("TVDB id (optional)") as HTMLInputElement;
    const create = screen.getByRole("button", { name: "Create" }) as HTMLButtonElement;

    expect(title.required).toBe(true);
    expect(folder.required).toBe(true);

    fireEvent.input(title, { target: { value: "The Public Archive" } });
    fireEvent.input(tvdb, { target: { value: "not-a-number" } });

    expect(create.disabled).toBe(false);
    expect(tvdb.validity.patternMismatch).toBe(true);
    expect(screen.getByRole("alert").textContent).toBe("TVDB id must be digits");

    fireEvent.click(create);
    expect(onCreate).not.toHaveBeenCalled();
  });
});
