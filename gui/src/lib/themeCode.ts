// Portable custom-theme share-code (Wave 3 T8). VENDORED PARITY TWIN of gui/src/lib/themeCode.ts —
// byte-identical logic so a code copied on one platform decodes on the other. Custom themes are
// device-local (never hub-synced); this string IS the portability mechanism.
//
// Format: `st1:` + the 9 editable slots as 6-hex each (no `#`), concatenated in the fixed ORDER below
// = 54 hex chars. The 4 semantic-state colors + derived slots are NOT encoded (state is locked, derived
// is recomputed on import), so the code carries only what the user actually edited.

export type EditableSlot =
  | "bg" | "surface" | "surface2" | "border" | "text1" | "text2" | "text3" | "accent" | "glassBg";

// Fixed order — do NOT reorder (it's the wire format; a reorder silently corrupts every existing code).
export const EDITABLE_ORDER: readonly EditableSlot[] = [
  "bg", "surface", "surface2", "border", "text1", "text2", "text3", "accent", "glassBg",
] as const;

export function encodeTheme(slots: Record<EditableSlot, string>): string {
  return "st1:" + EDITABLE_ORDER.map((k) => slots[k].replace("#", "").toLowerCase()).join("");
}

export function decodeTheme(code: string): Record<EditableSlot, string> | null {
  const m = /^st1:([0-9a-fA-F]{54})$/.exec(code.trim());
  if (!m) return null;
  const hex = m[1].toLowerCase();
  const out = {} as Record<EditableSlot, string>;
  EDITABLE_ORDER.forEach((k, i) => {
    out[k] = "#" + hex.slice(i * 6, i * 6 + 6);
  });
  return out;
}
