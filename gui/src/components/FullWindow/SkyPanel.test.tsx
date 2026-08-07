/**
 * SkyPanel.test.tsx — pins the tick rail's hand-rolled `role="slider"` keyboard contract (s156, D-B).
 *
 * ★ Adapted from the plan's verbatim text in two places, both because of this repo's own test
 * conventions, not a design change:
 *   - THIS REPO HAS NO jest-dom (see FolderImportPanel.test.tsx's own header comment) — `toHaveAttribute`
 *     and `toBeInTheDocument` don't exist here (`Invalid Chai property`, confirmed red). Replaced with
 *     `.getAttribute()` reads and a truthy check on the query result, same assertions either way.
 *   - `vitest.config.ts` does not set `globals: true`, so `@testing-library/react`'s auto-cleanup never
 *     registers itself. Every other component test file here (`NoteEditor.test.tsx`,
 *     `FolderImportPanel.test.tsx`, ...) manually calls `cleanup()` in `afterEach` for exactly this
 *     reason; without it, this file's five `render()` calls all landed in the same document and
 *     `getByRole("slider", ...)` failed with "Found multiple elements" (confirmed red).
 */
import { fireEvent, render, screen, cleanup } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import SkyPanel from "./SkyPanel";
import { DENSITY_STEPS } from "../../lib/starsSim";

afterEach(() => {
  cleanup();
});

const base = {
  open: true, onOpenChange: () => {}, densityIndex: 2, onDensityChange: () => {},
  smartConnections: false, onSmartConnectionsChange: () => {}, scale: 1,
  onZoomIn: () => {}, onZoomOut: () => {}, onZoomReset: () => {}, edgeCount: 39,
};

describe("SkyPanel", () => {
  it("exposes the rail as a slider with the real ARIA range", () => {
    render(<SkyPanel {...base} />);
    const rail = screen.getByRole("slider", { name: /density/i });
    expect(rail.getAttribute("aria-valuemin")).toBe("1");
    expect(rail.getAttribute("aria-valuemax")).toBe(String(DENSITY_STEPS.length));
    expect(rail.getAttribute("aria-valuenow")).toBe("3");
    expect(rail.getAttribute("aria-valuetext")).toBe("Balanced");
  });

  it("drives density from the keyboard in both directions and to both ends", () => {
    const onDensityChange = vi.fn();
    render(<SkyPanel {...base} onDensityChange={onDensityChange} />);
    const rail = screen.getByRole("slider", { name: /density/i });
    fireEvent.keyDown(rail, { key: "ArrowRight" });
    expect(onDensityChange).toHaveBeenLastCalledWith(3);
    fireEvent.keyDown(rail, { key: "ArrowLeft" });
    expect(onDensityChange).toHaveBeenLastCalledWith(1);
    fireEvent.keyDown(rail, { key: "Home" });
    expect(onDensityChange).toHaveBeenLastCalledWith(0);
    fireEvent.keyDown(rail, { key: "End" });
    expect(onDensityChange).toHaveBeenLastCalledWith(DENSITY_STEPS.length - 1);
  });

  it("cannot step past either end", () => {
    const onDensityChange = vi.fn();
    const { rerender } = render(<SkyPanel {...base} densityIndex={0} onDensityChange={onDensityChange} />);
    fireEvent.keyDown(screen.getByRole("slider", { name: /density/i }), { key: "ArrowLeft" });
    expect(onDensityChange).toHaveBeenLastCalledWith(0);
    rerender(<SkyPanel {...base} densityIndex={DENSITY_STEPS.length - 1} onDensityChange={onDensityChange} />);
    fireEvent.keyDown(screen.getByRole("slider", { name: /density/i }), { key: "ArrowRight" });
    expect(onDensityChange).toHaveBeenLastCalledWith(DENSITY_STEPS.length - 1);
  });

  it("names the current step and the resulting connection count", () => {
    render(<SkyPanel {...base} />);
    expect(screen.getByText(/Balanced/)).toBeTruthy();
    expect(screen.getByText(/39/)).toBeTruthy();
  });

  it("collapses to a single control that reopens it", () => {
    const onOpenChange = vi.fn();
    render(<SkyPanel {...base} open={false} onOpenChange={onOpenChange} />);
    expect(screen.queryByRole("slider")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /sky/i }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });
});
