// @vitest-environment happy-dom
/**
 * CompactShell.test.tsx — the structural contract the pill's morph depends on.
 *
 * Why this exists (s143, V2 redesign Phase 0): the compact panel's reveal is
 * pure CSS keyed off the `.compact-panel` element, its `.open` class and its
 * `data-zone`/`data-corner` attributes (see index.css `.compact-panel`, the
 * zone-directed clip-path, and the `.island-panel` overrides). Until now NO
 * test mounted this DOM — the pill suite asserts pure geometry functions only.
 * That meant renaming a class, dropping an attribute, or restructuring the
 * header could ship green while the morph silently stopped animating, or the
 * panel grew blank-but-open (the documented "dead/blank window until restart"
 * regression class).
 *
 * These assertions are deliberately structural, not visual: happy-dom has no
 * layout engine, so nothing here measures pixels. The point is that the hooks
 * the CSS binds to still exist and still respond to props.
 *
 * The upcoming V2 port rewrites what panels CONTAIN. If it also changes this
 * shell's shape, these tests should fail — that failure is the signal to stop
 * and check the motion, not to update the expectations.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import CompactShell from "./CompactShell";

afterEach(cleanup);

function renderShell(overrides: Partial<React.ComponentProps<typeof CompactShell>> = {}) {
  const props = {
    target: "vault" as const,
    corner: "rounded" as const,
    zone: "bottom" as const,
    open: true,
    onClose: vi.fn(),
    showClose: false,
    children: <div data-testid="body-content">panel body</div>,
    ...overrides,
  };
  const utils = render(<CompactShell {...props} />);
  const panel = utils.container.querySelector(".compact-panel") as HTMLElement;
  return { ...utils, panel, props };
}

describe("CompactShell — CSS binding surface", () => {
  it("renders the .compact-panel element the reveal transition is bound to", () => {
    const { panel } = renderShell();
    expect(panel).not.toBeNull();
  });

  // `.open` is what resolves clip-path to inset(0). Without it the panel is
  // grown but invisible — the blank-but-open failure mode.
  it("carries .open only when open is true", () => {
    const { panel } = renderShell({ open: true });
    expect(panel.classList.contains("open")).toBe(true);
    cleanup();
    const closed = renderShell({ open: false });
    expect(closed.panel.classList.contains("open")).toBe(false);
  });

  // data-zone picks which edge the clip sweeps from, so the panel always
  // unfurls away from the bar. A missing/incorrect zone reverses the wipe.
  it("reflects the extrude zone as data-zone", () => {
    const { panel } = renderShell({ zone: "top" });
    expect(panel.getAttribute("data-zone")).toBe("top");
    cleanup();
    expect(renderShell({ zone: "bottom" }).panel.getAttribute("data-zone")).toBe("bottom");
  });

  // data-corner drives the 12px-vs-0 radius split between rounded and sharp.
  it("reflects the corner style as data-corner", () => {
    expect(renderShell({ corner: "rounded" }).panel.getAttribute("data-corner")).toBe("rounded");
    cleanup();
    expect(renderShell({ corner: "sharp" }).panel.getAttribute("data-corner")).toBe("sharp");
  });

  // The content-lift transition targets `.compact-swap` inside the panel body;
  // children must land inside the panel, not beside it.
  it("renders children inside the panel body", () => {
    const { panel } = renderShell();
    const body = panel.querySelector(".compact-panel-body");
    expect(body).not.toBeNull();
    expect(body!.contains(screen.getByTestId("body-content"))).toBe(true);
  });
});

describe("CompactShell — header contract", () => {
  it("always renders the title header", () => {
    const { panel } = renderShell();
    expect(panel.querySelector(".compact-panel-header")).not.toBeNull();
    expect(panel.querySelector(".compact-panel-title")).not.toBeNull();
  });

  // Panels lift their own controls into this slot via onHeaderActionsChange
  // rather than rendering a duplicate header row of their own.
  it("renders headerActions into the header", () => {
    const { panel } = renderShell({ headerActions: <button data-testid="hdr-action">R</button> });
    const header = panel.querySelector(".compact-panel-header")!;
    expect(header.contains(screen.getByTestId("hdr-action"))).toBe(true);
  });

  // Capsule mode passes showClose={false} because clicking the bar closes the
  // panel; the minimal island passes true because it has no bar to click off.
  // Dropping the island's ✕ would remove its only close affordance.
  it("shows the close button only when showClose is set", () => {
    expect(renderShell({ showClose: false }).panel.querySelector(".compact-panel-close")).toBeNull();
    cleanup();
    expect(renderShell({ showClose: true }).panel.querySelector(".compact-panel-close")).not.toBeNull();
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    const { panel } = renderShell({ showClose: true, onClose });
    (panel.querySelector(".compact-panel-close") as HTMLButtonElement).click();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // RC-1: the pill window's outer wrapper closes the panel on any click, so
  // interior clicks must not bubble out to it. One choke point on the panel
  // root covers header, headerActions and body.
  //
  // The wrapper below is a React onClick, matching production (PillOverlay).
  // That distinction is load-bearing: React 18 delegates every handler to the
  // root container, so a *native* listener on that container would still fire
  // — stopPropagation only halts React's synthetic propagation to ancestor
  // handlers, which is exactly what the real click-to-close is.
  it("stops interior clicks from reaching the window's click-to-close", () => {
    const outer = vi.fn();
    const { container } = render(
      <div onClick={outer}>
        <CompactShell
          target="vault"
          corner="rounded"
          zone="bottom"
          open
          onClose={vi.fn()}
          showClose={false}
        >
          <div data-testid="inner">body</div>
        </CompactShell>
      </div>,
    );
    (container.querySelector(".compact-panel-body") as HTMLElement).click();
    expect(outer).not.toHaveBeenCalled();
  });
});

describe("CompactShell — panel crash auto-collapse", () => {
  // C2: a render throw inside a panel collapses back to the pill rather than
  // permanently blanking a grown window. The boundary is keyed by target so
  // switching panels always mounts a fresh one.
  it("closes the panel and reports the error when a child throws", () => {
    const onClose = vi.fn();
    const onPanelError = vi.fn();
    const Boom = () => { throw new Error("panel exploded"); };
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});

    renderShell({ onClose, onPanelError, children: <Boom /> });

    expect(onPanelError).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });
});
