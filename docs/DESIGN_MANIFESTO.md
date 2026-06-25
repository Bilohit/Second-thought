# Design Manifesto

## Core Design Philosophy

This document is a tutorial, but its surface — the monochrome palette, the quiet glow, the deliberate pacing of scroll reveals — is the same philosophy that governs Omni Capture itself: **speed and low friction over decoration.**

The product exists to remove a decision (where does this go?) from the user's path. The interface around it should not reintroduce decisions or distractions. Every visual choice in Deliverable 2 follows from that: nothing competes for attention with the content, nothing demands a choice the user didn't come here to make. Color is restrained so the eye is never asked "which thing matters here?" — the answer is always "the text." Motion is present but is information, not decoration: it tells you something appeared, not "look how impressive this is."

This is the same instinct as the scratchpad fallback in the pipeline — when the system isn't sure, it doesn't force a confident wrong answer onto the user. The UI mirrors that: when in doubt, recede.

## Typography and Space

**Inter** for prose, **JetBrains Mono** for code — one humanist, highly legible sans for reading at length, one monospace built specifically for code legibility (disambiguated `0`/`O`, `1`/`l`/`I`) for anything technical. This is the same reasoning as the codebase's own convention of not introducing a tool for a job a narrower one already does well: a general sans face for general reading, a code face for code, no third "display" face competing for identity.

The generous padding (`4rem 1.5rem` outer, `1.75rem` inner) and the `760px` max-width are not aesthetic indulgence — they are the same low-friction principle applied to the eye instead of the hand. A 760px column keeps line length in the comfortable reading range without forcing the reader to track lines across a wide viewport, the same way the single-pill capture flow keeps the user from tracking multiple steps to file one note. Whitespace here is doing the job the scratchpad does in the pipeline: giving each idea room to be unambiguous before the next one starts.

## Color Theory

The palette is monochrome by design: pure black/white extremes for `--bg`, near-black/near-white for `--surface`, a single muted border tone, and a glow color that is just the inverse of the text color at low opacity. There is exactly one accent color (`--accent`), reserved for the two places where the user is meant to notice motion deliberately: the theme toggle on hover and the pro-tip callouts.

This restraint mirrors the product's own categorization philosophy — Omni Capture never invents a fixed taxonomy of categories, it reflects back what's already structurally present in the vault. The design system does the same with color: it doesn't introduce a palette of meaning (red for danger, green for success, blue for info) where no such distinctions exist on this page. One accent, used sparingly, says "this is worth a second look" without building out a whole semantic color language the content never needed.

The glow itself — a soft `box-shadow`/`text-shadow` derived from `--glow-color` — exists so that hierarchy and hover state can be communicated through light intensity rather than added color or added chrome. It's a single extra dimension layered onto an otherwise flat, two-tone surface, the same way the radial menu in the actual app adds one extra interaction surface to an otherwise minimal pill, rather than stacking on multiple new UI chromes.

## Interaction Design

Motion in this document follows a strict rule: **it earns attention, it doesn't demand it.**

- **Scroll reveals** (`anim-fade-up`, `anim-scale-in`) only ever move content the small distance and short duration needed to register as "this just appeared," not as a performance. They fire once, via `IntersectionObserver`, and then get out of the way — exactly like a capture confirmation that flashes once and dismisses, not a persistent banner.
- **Staggered delays** (`.delay-1` through `.delay-10`) exist so that when multiple elements enter together, the eye is given an implicit reading order instead of being asked to scan a wall of simultaneous motion. This is the same instinct behind the pipeline's 4-stage sequence being surfaced to the user one stage at a time over SSE rather than as a single opaque "working…" spinner — sequence communicates progress, and progress earns trust.
- **Hover states** (Y-axis lift, glow-based shadow, border color shift) are reserved for elements that are actually interactive or that benefit from being singled out for closer reading (a `<section>`, the CTA box). Nothing animates just because animation is available.
- **The pulsing pro-tip border** is the one piece of ambient, looping motion on the page, and it is used exactly once per callout type — a soft, slow pulse (4 seconds) that reads as "this is worth pausing on," not as urgency or alarm.
- **`prefers-reduced-motion` is honored unconditionally** — all transitions and animations collapse to instant, fully-visible states. A user who has told their OS they don't want motion gets the same content with none of the choreography, never a degraded or broken layout.

None of this is ornamental for its own sake. Every animation in this document is doing the same job the pipeline's two-pass retry does in the backend: giving the user one more honest signal about what's actually happening, and stopping there.
