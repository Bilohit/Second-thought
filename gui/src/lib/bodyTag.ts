/**
 * Client mirror of `omni_capture/body_tags.py`'s `is_valid_body_tag` (SP3 Task 10).
 *
 * The daily-note tag is a free-text settings field, and `SettingsPanel` resends the WHOLE field
 * set on every save — the exact shape that made FR-01 take down every control on the Function tab
 * when one field was rejected. So the value is validated here, before it can ride along in a
 * PATCH and 400 the rest of the tab with it.
 *
 * Kept deliberately identical to the Python, including its two silent-drop rules — the scanner
 * drops a 3/6-hex-digit token as a bare colour, and structural tags (`sys`, `sys/*`, `project@*`)
 * never reach the derived `tags:` cache (`project@x` would additionally FILE the note into a
 * project, which this field must never be a back door into). Drift the two and the GUI will
 * happily accept a tag the server rejects, or worse, one the server accepts and the scanner eats.
 */

const WHOLE_TAG = /^[A-Za-z0-9_@][A-Za-z0-9_/@:-]*$/;
const HEX_COLOR = /^[0-9A-Fa-f]{3}$|^[0-9A-Fa-f]{6}$/;

/** Mirror of `projects.is_structural_tag`. */
function isStructuralTag(tag: string): boolean {
  return tag === "sys" || tag.startsWith("sys/") || tag.startsWith("project@");
}

/** True when writing `#<tag>` into a note body would really produce that tag. */
export function isValidBodyTag(tag: string): boolean {
  return WHOLE_TAG.test(tag) && !HEX_COLOR.test(tag) && !isStructuralTag(tag);
}

/** What the user typed, normalised the way the server stores it (a leading `#` is forgiven). */
export function normalizeBodyTag(raw: string): string {
  return raw.trim().replace(/^#+/, "");
}

/** The one message both the empty and the malformed case show. Kept next to the rule it explains. */
export const BODY_TAG_HINT =
  "Letters, digits, _ / @ : or - — no spaces, and not a sys or project@ tag.";
