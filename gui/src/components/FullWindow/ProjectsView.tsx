/**
 * ProjectsView.tsx — sub-project 3 Task 4/5: the full-window Projects
 * screen's container. Owns the listProjects() fetch, the selected
 * project/loose bucket, and the rail's projects|tags view mode. Renders
 * <ProjectsRail/> on the left (260px, spec §3) and <ProjectsPane/> on the
 * right (Task 5: head, rename/delete, description editor, notes-head count
 * + sort instrument, note rows, delete-confirm strip).
 *
 * Task 8 owns wiring this component into LibraryView/FullWindow in place of
 * the current `vault` section — not built here.
 *
 * Board: gui/mocks/2026-08-01-projects-fullwindow-v3.html. Spec: docs/
 * superpowers/specs/2026-08-02-projects-s3-fullwindow-design.md.
 */
import { useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import ProjectsRail, { LOOSE_PROJECT_ID, type RailMode } from "./ProjectsRail";
import ProjectsPane from "./ProjectsPane";
import { listProjects, getStats, type ProjectEntry } from "../../lib/api";

interface Props {
  visible: boolean;
  onOpenNote?: (path: string) => void;
}

export default function ProjectsView({ visible, onOpenNote }: Props) {
  const [mode, setMode] = useState<RailMode>("projects");
  const [projects, setProjects] = useState<ProjectEntry[]>([]);
  // Every tile's count (loose included, under LOOSE_PROJECT_ID) comes from
  // ONE map built off getStats().by_project — the index's project column
  // (index_writer.py `SELECT project, COUNT(*) ... GROUP BY project`),
  // derived from the body tag. NOT ProjectEntry.file_count, which is
  // vault_admin._project_file_count counting .md files in a directory — the
  // exact directory-derived count s127 ripped out of the index (board lines
  // 335/448). The pane's note list (Task 5, GET /search?project=<name>)
  // reads the same project column, so this is the one source that can never
  // disagree with it by construction (spec §5.6: never a count from one
  // source beside a list from another).
  const [projectCounts, setProjectCounts] = useState<Record<string, number>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Shared by first-load and the rename/delete refetch (spec: "the rail's
  // tiles and counts are stale" after either succeeds — refetch BOTH
  // listProjects() and getStats() rather than letting the two surfaces
  // disagree). `keepSelection` is false only on first load, where the
  // board's own default (§ below) should apply instead of preserving a
  // (nonexistent yet) prior selection.
  const refresh = useCallback(() => {
    let cancelled = false;

    listProjects().then(({ projects: rows }) => {
      if (cancelled) return;
      setProjects(rows);
      // First open only (never overwrites a live selection): the first
      // project, or the loose bucket when the vault has none yet. Inferred
      // from the board's own mount() default (`sel: empty ? "__loose" :
      // "research"`) — the spec does not state an explicit rule for the
      // Projects half the way §5.2 does for Tags ("switching to Tags
      // selects the first tag"), so this is a judgment call, not a spec'd
      // behavior. Flagged in this task's report.
      setSelectedId((prev) => prev ?? (rows[0]?.name ?? LOOSE_PROJECT_ID));
    }).catch(() => { if (!cancelled) setProjects([]); });

    getStats().then((stats) => {
      if (cancelled) return;
      const counts: Record<string, number> = {};
      for (const row of stats.by_project) counts[row.project] = row.count;
      // A registered project with zero captures simply has no row here —
      // ProjectsRail's `projectCounts[p.name] ?? 0` renders "0 notes" for
      // it, never "undefined notes" and never a vanished tile.
      setProjectCounts(counts);
    }).catch(() => { if (!cancelled) setProjectCounts({}); });

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!visible) return;
    return refresh();
  }, [visible, refresh]);

  if (!visible) return null;

  return (
    <div style={containerStyle}>
      <ProjectsRail
        mode={mode}
        onModeChange={setMode}
        projects={projects}
        projectCounts={projectCounts}
        looseCount={projectCounts[LOOSE_PROJECT_ID] ?? 0}
        selectedId={selectedId}
        onSelect={setSelectedId}
        // Presentational only (see ProjectsRail.tsx's file header) — Task 4
        // does not call GET /inbox/{note_id}/suggest-projects or invent
        // which note_id this screen's "one Inbox suggestion" (spec §1) is
        // even for. That data source needs its own decision, not a guess
        // made here; left null rather than fabricated. See this task's report.
        suggestion={null}
        onNewProject={() => { /* Task 5/8: create-project flow — no modal exists on the board either. */ }}
      />
      <ProjectsPane
        projects={projects}
        selectedId={selectedId}
        onOpenNote={onOpenNote}
        onRenamed={(oldName, newName) => {
          setSelectedId((prev) => (prev === oldName ? newName : prev));
          refresh();
        }}
        onDeleted={(name) => {
          setSelectedId((prev) => (prev === name ? LOOSE_PROJECT_ID : prev));
          refresh();
        }}
        onDescriptionSaved={(name, description) => {
          // The description save itself doesn't change any COUNT (getStats
          // is untouched by it), only the registry's `description` field —
          // patch that field in place rather than a full listProjects()
          // round trip on every debounced keystroke-save.
          setProjects((prev) => prev.map((p) => (p.name === name ? { ...p, description } : p)));
        }}
      />
    </div>
  );
}

const containerStyle: CSSProperties = { flex: 1, minHeight: 0, display: "flex", overflow: "hidden" };
