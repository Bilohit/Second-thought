# Minimal-mode menu: staggered open animation

## Goal

In **Minimal** display mode, the radial spoke menu animates **out** with a nice
staggered fan (each spoke leaves a little after the previous one), but it
appears **in** all at once — no stagger. We want the **open** animation to use
the same staggered fan-in that the close already has.

This is purely a frontend (React/CSS) change in the GUI. It does **not** touch
the Python pipeline.

---

## Where the code lives

- `gui/src/components/PillMenu/RadialMenu.tsx` — renders the spokes (minimal mode).
- `gui/src/index.css` — `.spoke` / `.spoke.open` rules (lines ~624–693).
- `gui/src/components/PillOverlay.tsx` — mounts `<RadialMenu>` (line ~120).
- `gui/src/App.tsx` — computes `radialGeometry` asynchronously when the menu
  opens (lines ~618–665). **This async timing is the root cause** — see below.

The capsule-mode menu (`CapsuleMenu.tsx`) already staggers correctly on **both**
open and close. The difference in *why* is the whole key to this bug.

---

## How the stagger is supposed to work

Each spoke gets an inline `transitionDelay: ${i * RADIAL_STAGGER_MS}ms`
(`RadialMenu.tsx:135`, `RADIAL_STAGGER_MS = 45`). The CSS transitions `opacity`
and `transform` over `--spoke-anim-ms` (260ms):

```css
.spoke      { opacity: 0; transform: translate(0,0) scale(0.6); transition: transform …, opacity …; }
.spoke.open { opacity: 1; transform: translate(var(--tx), var(--ty)) scale(1); }
```

A staggered animation happens when the browser sees a **state change** from the
closed rule to the `.open` rule (or vice-versa): each spoke's per-element
`transition-delay` then offsets when its transition begins. The delay applies
equally to entering and leaving, so in principle both directions should stagger.

---

## Root cause: spokes are born already-open, so there is no enter transition

The radial spokes are **not** persistently mounted. They are rendered only when
`fan.items` is non-empty, and `fan.items` is empty until `pillGeometry`
(a.k.a. `radialGeometry` in `App.tsx`) is populated:

- `RadialMenu.tsx:67-86` — `unifiedFan(...)` returns `{ items: [] }` when
  `pillGeometry` is null, so **zero spokes render**.
- `App.tsx:258` — `radialGeometry` starts `null`.
- `App.tsx:664` — on close it is set back to `null`.
- `App.tsx:630-639` — it is only populated **inside an async effect** (after
  several `await getCurrentWindow()…` calls), which runs *after* `menuOpen` has
  already flipped to `true`.

So the open sequence is:

1. `menuOpen` → `true`. `radialGeometry` is still `null` → **no spokes exist**.
2. The async effect resolves and calls `setRadialGeometry(...)`.
3. Spokes render **for the first time** — but `menuOpen` is *already* `true`, so
   on their very first commit they already carry the `.open` class and the
   open-state CSS values.

Because their first-ever rendered state *is* the open end-state, the browser has
no closed→open change to transition between. They simply pop into place. The
`transition-delay` is irrelevant when there is no transition to delay.

**Close works** for the mirror-image reason: when closing, the spokes are
already mounted in the open state, so removing `.open` is a real open→closed
state change, the exit transition fires, and the per-spoke delays stagger it.

### Why the capsule doesn't have this bug (confirmation of the diagnosis)

In `CapsuleMenu.tsx` the six `.capsule-item`s are **always** in the DOM as
children of the bar (rendered regardless of `open`, just `width:0; opacity:0`
when closed — `index.css:774-797`). They are present in the closed state *before*
`open` flips, so flipping `open` is a genuine closed→open change and the
staggered enter transition plays. The radial spokes lack this because their
existence is gated on async geometry.

---

## The fix

Force a real closed→open transition by ensuring the spokes are first committed
in the **closed** state, then flipped to open on a subsequent frame. Do this
locally inside `RadialMenu.tsx` with an internal "entered" state, decoupled from
the `open` prop. The `.open` class should be driven by `entered`, not directly
by `open`.

### Behavior we must preserve

- **Close must still stagger.** So `entered` must drop to `false` *immediately*
  when `open` becomes `false` (synchronously, no rAF) — that reproduces today's
  working exit transition.
- **Re-open must re-trigger.** Resetting `entered` to `false` on close means the
  next open is again a false→true change.
- Reduced-motion is already handled in CSS (`index.css:856-867` zeroes the
  delay) — no change needed there.

### Implementation in `RadialMenu.tsx`

1. Add internal state:

   ```tsx
   const [entered, setEntered] = useState(false);
   ```

2. After `positions` is derived, add an effect that flips `entered` once the
   spokes actually exist and the menu is open. Use a **double**
   `requestAnimationFrame` so the browser is guaranteed to paint the closed
   state on one frame before the open state is applied on the next (a single
   rAF/effect can still batch with the initial paint and skip the transition):

   ```tsx
   useEffect(() => {
     if (open && positions.length > 0) {
       let r2 = 0;
       const r1 = requestAnimationFrame(() => {
         r2 = requestAnimationFrame(() => setEntered(true));
       });
       return () => { cancelAnimationFrame(r1); cancelAnimationFrame(r2); };
     }
     // Closing (or no geometry yet): drop instantly so the existing staggered
     // exit transition still fires, and the next open re-triggers the enter.
     setEntered(false);
   }, [open, positions.length]);
   ```

3. Drive the `.open` class from `entered` instead of `open`:

   ```tsx
   className={`spoke${isHide ? " spoke-hide" : ""}${entered ? " open" : ""}`}
   ```

   Leave the rest (`--tx`, `--ty`, `transitionDelay: ${i * RADIAL_STAGGER_MS}ms`,
   `tabIndex={open ? 0 : -1}`, focus effect keyed on `open`) unchanged.
   `tabIndex` and the focus effect should stay keyed on `open`, not `entered`,
   so keyboard focus still lands as soon as the menu opens.

That's the whole change. No CSS edits, no `App.tsx` edits required.

---

## Why not "just compute geometry synchronously"

`radialGeometry` depends on live Tauri window position/size + active monitor
work-area (`App.tsx:622-639`), which are async calls. We can't make them
synchronous, so we can't simply have the spokes mount closed at the same render
`menuOpen` flips. The two-frame mount technique inside `RadialMenu` is the
correct, localized fix and is robust to the geometry arriving on any later
frame (the effect deps include `positions.length`, so it triggers whenever the
spokes first appear).

---

## How to verify

1. `cd gui && npm run dev` (or `.\launch.ps1`).
2. Settings → Display Mode → **Minimal**, rounded or sharp.
3. Trigger the pill, click it to **open** the menu: spokes should now fan in one
   after another (≈45ms apart), matching the existing fan-out on close.
4. Click again to **close**: the staggered exit must be unchanged from before.
5. Open/close several times in a row — every open must re-trigger the stagger
   (verifies `entered` resets on close).
6. Tab into the menu right after opening — focus should still land on the first
   spoke immediately (verifies focus/`tabIndex` still keyed on `open`).
7. Enable OS "reduce motion" and confirm the menu still appears/disappears
   instantly with no stagger (CSS already handles this).

## Acceptance criteria

- Minimal-mode menu **open** animates with the same staggered fan as **close**.
- Close animation is visually identical to today.
- Repeated open/close keeps working.
- No regression to keyboard focus, reduced-motion, or capsule mode.
