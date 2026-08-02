import ProjectsView from "./ProjectsView";
import TrashView from "./TrashView";

interface Props {
  visible: boolean;
  /** vault/trash section — owned by FullWindow so its toggle can live in
   *  the topbar (like the Look search/chat toggle). */
  section: "vault" | "trash";
  /** F-7 follow-up: opens a file in the full-window NoteEditor (threaded
   *  from FullWindow's setEditorPath). */
  onOpenNote?: (path: string) => void;
}

export default function LibraryView({ visible, section, onOpenNote }: Props) {
  if (!visible) return null;

  // FR-06 fix: <ProjectsView> stays mounted across the Projects|Trash
  // toggle instead of being conditionally rendered with `section === "vault"
  // && <ProjectsView/>`. That old gate unmounted the component entirely on
  // every switch to Trash, resetting its local `mode`/`selectedId`/
  // `selectedTag` state — a chosen tag filter was silently discarded the
  // moment the user glanced at Trash. ProjectsView already threads a
  // `visible` prop that (a) returns null from render while hidden, so no
  // DOM/CSS cost while in Trash, and (b) gates its data-fetch effects on
  // that same prop, so switching to Trash does NOT leave background
  // fetches running — the real cost the two-shapes tradeoff warns about is
  // already avoided by this prop existing. That made "keep mounted, hide"
  // strictly simpler than lifting mode/selectedId/selectedTag into this
  // component and threading them back down as controlled props, with no
  // downside: state survives the round trip, first-visit defaults
  // (rows[0] ?? loose, first tag on switching to Tags) are untouched
  // because they only run once on the initial fetch, never on a
  // visible:false -> true flip with existing state.
  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 14, padding: 14, overflow: "hidden" }}>
      <ProjectsView visible={section === "vault"} onOpenNote={onOpenNote} />
      {section === "trash" && (
        <div style={{ flex: 1, minHeight: 0, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <TrashView visible />
        </div>
      )}
    </div>
  );
}
