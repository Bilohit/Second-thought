/**
 * useDragCloseOnMove.ts
 * ---------------------
 * for_sonnet.md "Problem 4" decision #4b: dragging the pill closes the menu
 * instead of being locked while it's open. The OS-level drag (`.drag-region`
 * / `-webkit-app-region: drag`) still does the actual window move — this
 * hook only watches for pointer movement past a small threshold while the
 * menu is open and fires a callback to close it, so a plain click (no
 * meaningful movement) still reaches the toggle handler untouched.
 */
import { useRef } from "react";

const DRAG_THRESHOLD_PX = 4;

export function useDragCloseOnMove(active: boolean, onDragStart: () => void) {
  const startRef = useRef<{ x: number; y: number } | null>(null);
  const firedRef = useRef(false);

  const onPointerDown = (e: React.PointerEvent) => {
    startRef.current = { x: e.clientX, y: e.clientY };
    firedRef.current = false;
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (!active || firedRef.current || !startRef.current) return;
    const dx = e.clientX - startRef.current.x;
    const dy = e.clientY - startRef.current.y;
    if (Math.hypot(dx, dy) > DRAG_THRESHOLD_PX) {
      firedRef.current = true;
      onDragStart();
    }
  };
  const onPointerUp = () => {
    startRef.current = null;
  };

  return { onPointerDown, onPointerMove, onPointerUp };
}
