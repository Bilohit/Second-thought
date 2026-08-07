/// <reference types="vite/client" />
/**
 * Mount census — every component renders once. The assertion is only "does not throw".
 *
 * This rung exists because unit-green surfaces have shipped visually broken: s151's RNGH
 * `onEnd` bug was unreachable code that a fully green suite never reported. A census cannot
 * catch that class on its own, but it catches every surface that throws the moment it is
 * asked to render — which no other gate here does.
 *
 * Scope note: this file censuses what EXISTS. Whether a component is REACHABLE from the app
 * entry is a different question, owned by tools/reachability.py. Both run in tier 1; neither
 * substitutes for the other. Five components that used to be censused here and unreachable
 * there (DashboardView, LibraryView, ProjectsPane, ProjectsRail, ProjectsView) were deleted
 * in the bounded dead-code cleanup (CURRENT.md §5.8) once their capabilities were confirmed
 * live elsewhere (BrowseView's drill-in, InboxPanel's Reminders tab, NotesView).
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import React from "react";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => null) }));
vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(async () => () => {}),
  emit: vi.fn(async () => {}),
}));
vi.mock("@tauri-apps/api/window", () => ({
  getCurrentWindow: () => ({
    setSize: vi.fn(async () => {}),
    setPosition: vi.fn(async () => {}),
    outerPosition: vi.fn(async () => ({ x: 0, y: 0 })),
    scaleFactor: vi.fn(async () => 1),
    listen: vi.fn(async () => () => {}),
  }),
}));

/**
 * The census asserts "this surface renders" — never "the backend answered". Left unstubbed,
 * happy-dom's `fetch` is REAL: every mounted panel issued live requests to the desktop server on
 * :7070, so this rung's result depended on whether that process was running and how fast it
 * answered while ~85 other test files mounted their own panels in parallel workers. That is how
 * it failed at s157 — `CompactSettings` alone needs ~1s to mount, and under full-suite contention
 * it crossed vitest's default 5s timeout, going red on a run whose product code was fine.
 *
 * The stub returns the SAME 403 those requests already got (the server rejects an unauthenticated
 * caller — `X-Omni-Secret` is never set here), so component behaviour is byte-for-byte what it was
 * before; only the network round-trip is gone. Raising the timeout instead would have left a unit
 * gate depending on an external process.
 */
vi.stubGlobal(
  "fetch",
  vi.fn(async () => new Response('{"detail":"Forbidden"}', {
    status: 403,
    headers: { "content-type": "application/json" },
  })),
);

const SURFACES = import.meta.glob("../components/**/*.tsx");

/**
 * Minimal props for components that cannot render bare. Deliberately dumb — the census
 * asserts "renders", not "behaves"; behaviour belongs in that component's own test file.
 * A component needing more than a few trivial props here is a signal about the component,
 * not about the census.
 */
const PROPS: Record<string, Record<string, unknown>> = {};

/**
 * Components that cannot render with no props at all. Being on this list is a DECLARATION,
 * not a pass: a component that throws bare and is NOT listed here fails the census, so a
 * newly-broken surface cannot slip through, and adding a name here is visible in the diff.
 *
 * ponytail: a declared exemption instead of 14 hand-written prop fixtures. Fixtures for
 * every component would be a maintenance surface larger than the census itself and would
 * rot the first time a prop type changed. Upgrade path: move a name from this list into
 * PROPS above whenever you are already in that component for another reason — each move
 * converts a declaration back into a real render assertion.
 */
const REQUIRES_PROPS = new Set([
  "../components/CompactPanels/CompactLook.tsx",
  "../components/FullWindow/FullWindow.tsx",
  "../components/FullWindow/NotesView.tsx",
  "../components/LookPanel.tsx",
  "../components/PillOverlay.tsx",
  "../components/StatusIndicator.tsx",
  "../components/StepIndicator.tsx",
  "../components/ThemeCustomEditor.tsx",
  "../components/Toast.tsx",
  "../components/ToastHost.tsx",
  "../components/ui/SegmentedToggle.tsx",
]);

describe("mount census", () => {
  afterEach(() => cleanup());

  it("has surfaces to census", () => {
    expect(Object.keys(SURFACES).length).toBeGreaterThan(0);
  });

  it("every declared exemption still exists", () => {
    // Stops the list rotting into names that no longer resolve, which would quietly
    // shrink the census while looking unchanged.
    const known = new Set(Object.keys(SURFACES));
    for (const p of REQUIRES_PROPS) expect(known.has(p), `stale exemption: ${p}`).toBe(true);
  });

  for (const path of Object.keys(SURFACES)) {
    if (path.includes(".test.")) continue;
    const name = path.replace("../components/", "");
    const exempt = REQUIRES_PROPS.has(path) && !PROPS[path];

    it(`renders ${name}${exempt ? " (declared: needs props)" : ""} without throwing`, async () => {
      const mod = (await SURFACES[path]()) as Record<string, unknown>;
      const Component = mod.default;
      if (typeof Component !== "function") return; // not a component module
      const C = Component as React.ComponentType<Record<string, unknown>>;
      if (exempt) {
        // Assert only that the module loads and exports a component. A declared exemption
        // must never assert a green render it did not perform.
        expect(typeof C).toBe("function");
        return;
      }
      expect(() => render(<C {...(PROPS[path] ?? {})} />)).not.toThrow();
    });
  }
});
