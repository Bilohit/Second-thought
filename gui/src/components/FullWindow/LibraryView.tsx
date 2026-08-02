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

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", gap: 14, padding: 14, overflow: "hidden" }}>
      {section === "vault" && <ProjectsView visible onOpenNote={onOpenNote} />}
      {section === "trash" && (
        <div style={{ flex: 1, minHeight: 0, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "var(--radius-sm)", overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <TrashView visible />
        </div>
      )}
    </div>
  );
}
